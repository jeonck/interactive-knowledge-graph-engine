"""Graph loaders: local files, networkx classics, and a live Wikipedia crawler."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import networkx as nx

API = "https://en.wikipedia.org/w/api.php"
UA = "interactive-knowledge-graph-engine/1.0 (https://graph-engine.metacog.co.kr)"
SKIP_PREFIX = ("List of", "Lists of", "Index of", "Outline of", "Timeline of",
               "Glossary of", "Comparison of", "History of")
# Citation and archive plumbing that every article links to; it is infrastructure,
# not knowledge, and it would dominate every centrality ranking.
SKIP_EXACT = {"Wayback Machine", "Digital object identifier", "ISBN", "ISSN",
              "PubMed", "PubMed Central", "ArXiv", "JSTOR", "Bibcode", "S2CID",
              "Doi (identifier)", "Internet Archive", "Google Books",
              "Library of Congress", "Semantic Scholar", "OCLC", "Google Scholar",
              "Springer Science+Business Media", "Elsevier", "Wikipedia",
              "Cambridge University Press", "Oxford University Press",
              "Princeton University Press", "MIT Press", "Association for Computing Machinery",
              "Institute of Electrical and Electronics Engineers", "CiteSeerX"}


def load_edgelist(path, directed=True):
    """CSV/TSV with a source,target[,weight] header, or a JSON {nodes,links}."""
    if str(path).endswith(".json"):
        data = json.load(open(path, encoding="utf-8"))
        G = nx.DiGraph() if directed else nx.Graph()
        G.add_nodes_from(n["id"] for n in data.get("nodes", []))
        G.add_edges_from((l["source"], l["target"], {"weight": float(l.get("weight", 1))})
                         for l in data["links"])
        return G
    with open(path, newline="", encoding="utf-8") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        rows = list(csv.DictReader(fh, dialect=dialect))
    if not rows:
        raise ValueError(f"{path}: no rows")
    cols = {c.lower(): c for c in rows[0]}
    src, tgt = cols.get("source"), cols.get("target")
    if not (src and tgt):
        raise ValueError(f"{path}: need 'source' and 'target' columns, got {list(rows[0])}")
    wcol = cols.get("weight")
    G = nx.DiGraph() if directed else nx.Graph()
    for r in rows:
        w = float(r[wcol]) if wcol and r.get(wcol) else 1.0
        G.add_edge(r[src].strip(), r[tgt].strip(), weight=w)
    return G


def les_miserables():
    G = nx.les_miserables_graph()
    return G


def karate():
    G = nx.karate_club_graph()
    return nx.relabel_nodes(G, {v: f"Member {v}" for v in G})


# --- Wikipedia -------------------------------------------------------------

CACHE = Path(os.environ.get("WIKI_CACHE", ".cache/wiki"))


def _get(url, tries=6):
    """GET with an on-disk cache and backoff; the API rate-limits hard."""
    key = CACHE / (hashlib.md5(url.encode()).hexdigest() + ".json")
    if key.exists():
        return json.loads(key.read_text(encoding="utf-8"))
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as fh:
                data = json.load(fh)
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps(data), encoding="utf-8")
    return data


def _api(params, pause=0.25):
    """One API call, following `continue` until the query is exhausted."""
    pages = {}
    params = dict(params, action="query", format="json", formatversion="2", redirects="1")
    while True:
        data = _get(API + "?" + urllib.parse.urlencode(params))
        time.sleep(pause)
        for page in data.get("query", {}).get("pages", []):
            cur = pages.setdefault(page["title"], {})
            for key, val in page.items():
                if isinstance(val, list):
                    cur.setdefault(key, []).extend(val)
                else:
                    cur.setdefault(key, val)
        if "continue" not in data:
            return pages
        params.update(data["continue"])
        time.sleep(pause)


def _batched(titles, size=25):
    titles = list(titles)
    for i in range(0, len(titles), size):
        yield titles[i:i + size]


def _keep(title):
    return not (title.startswith(SKIP_PREFIX) or title in SKIP_EXACT
                or "(disambiguation)" in title or "(identifier)" in title)


def wikipedia_graph(seeds, size=200, pvdays=30, log=print):
    """Build a directed link graph around `seeds`.

    Candidates = every article the seeds link to. They are ranked by real
    Wikipedia pageviews (last `pvdays` days), the top `size` are kept, and the
    graph is the actual wikilinks among that set.
    """
    log(f"fetching links for {len(seeds)} seeds ...")
    candidates = {}
    for batch in _batched(seeds, 10):
        for title, page in _api({"prop": "links", "plnamespace": "0",
                                 "pllimit": "max", "titles": "|".join(batch)}).items():
            for link in page.get("links", []):
                if _keep(link["title"]):
                    candidates[link["title"]] = candidates.get(link["title"], 0) + 1
    log(f"  {len(candidates)} candidate articles")

    log("ranking candidates by pageviews ...")
    views = {}
    titles = sorted(candidates, key=lambda t: -candidates[t])[:1500]
    for i, batch in enumerate(_batched(titles, 25)):
        for title, page in _api({"prop": "pageviews", "pvipdays": str(pvdays),
                                 "titles": "|".join(batch)}).items():
            daily = (page.get("pageviews") or {}).values()
            views[title] = sum(v for v in daily if v)
        if i % 10 == 0:
            log(f"  {min((i + 1) * 25, len(titles))}/{len(titles)}")

    keep = set(seeds) | set(sorted(views, key=lambda t: -views[t])[:size])
    log(f"fetching links among the {len(keep)} kept articles ...")
    G = nx.DiGraph()
    for title in keep:
        G.add_node(title, views=views.get(title, 0))
    for i, batch in enumerate(_batched(sorted(keep), 25)):
        for title, page in _api({"prop": "links", "plnamespace": "0",
                                 "pllimit": "max", "titles": "|".join(batch)}).items():
            if title not in G:
                continue
            for link in page.get("links", []):
                if link["title"] in G and link["title"] != title:
                    G.add_edge(title, link["title"], weight=1.0)
        if i % 4 == 0:
            log(f"  {min((i + 1) * 25, len(keep))}/{len(keep)}")

    G.remove_nodes_from([v for v, d in G.degree() if d == 0])
    log(f"graph: {G.number_of_nodes()} nodes / {G.number_of_edges()} edges")
    return G
