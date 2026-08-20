"""Command line: turn a network into a validated, browsable knowledge graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import networkx as nx

from . import datasets, engine

SITE_DATA = Path("docs/data")

BUILTIN = {
    "les-miserables": (datasets.les_miserables,
                       "Character co-occurrence network of Victor Hugo's Les Miserables.",
                       "Knuth, The Stanford GraphBase (1993)"),
    "karate": (datasets.karate,
               "Zachary's karate club: friendships in a university club that split in two.",
               "Zachary, J. Anthropological Research (1977)"),
}


def _progress(done, total):
    print(f"\r  null model {done}/{total}", end="", file=sys.stderr, flush=True)
    if done == total:
        print(file=sys.stderr)


def _write(G, args, name, description, source):
    print(f"analysing {G} with {args.rewires} rewirings ...", file=sys.stderr)
    result = engine.analyze(G, rewires=args.rewires, seed=args.seed, progress=_progress)
    payload = engine.to_site_json(G, result, name=name, description=description, source=source)
    out = Path(args.out) if args.out else SITE_DATA / f"{args.slug or _slug(name)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    g = payload["globals"]
    print(f"wrote {out}  ({g['nodes']} nodes, {g['edges']} edges, "
          f"modularity {g['modularity']} z={g['modularity_z']})", file=sys.stderr)
    if out.parent == SITE_DATA:
        _reindex(out, payload)
    return payload


def _slug(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def _reindex(path, payload):
    """Keep docs/data/index.json in sync with what is on disk."""
    index_path = SITE_DATA / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else []
    index = [d for d in index if d["file"] != path.name]
    index.append({"file": path.name, "name": payload["name"],
                  "description": payload["description"], "source": payload["source"],
                  "nodes": payload["globals"]["nodes"], "edges": payload["globals"]["edges"]})
    index.sort(key=lambda d: -d["nodes"])
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--rewires", type=int, default=50,
                        help="null-model samples per graph (default 50)")
    common.add_argument("--seed", type=int, default=0)
    common.add_argument("--out", help="output JSON path (default docs/data/<slug>.json)")
    common.add_argument("--slug")
    common.add_argument("--name")
    common.add_argument("--description", default="")
    common.add_argument("--source", default="")

    ap = argparse.ArgumentParser(prog="graphengine", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("file", parents=[common],
                       help="analyse a CSV/TSV edge list or {nodes,links} JSON")
    f.add_argument("path")
    f.add_argument("--undirected", action="store_true")

    b = sub.add_parser("builtin", parents=[common], help="analyse a bundled classic network")
    b.add_argument("dataset", choices=sorted(BUILTIN))

    w = sub.add_parser("wikipedia", parents=[common],
                       help="crawl a live Wikipedia link network")
    w.add_argument("seeds", nargs="+", help="seed article titles")
    w.add_argument("--size", type=int, default=200, help="articles to keep (default 200)")

    args = ap.parse_args(argv)

    if args.cmd == "file":
        G = datasets.load_edgelist(args.path, directed=not args.undirected)
        name = args.name or Path(args.path).stem
    elif args.cmd == "builtin":
        loader, desc, src = BUILTIN[args.dataset]
        G = loader()
        name = args.name or args.dataset.replace("-", " ").title()
        args.description = args.description or desc
        args.source = args.source or src
        args.slug = args.slug or args.dataset
    else:
        G = datasets.wikipedia_graph(args.seeds, size=args.size,
                                     log=lambda m: print(m, file=sys.stderr))
        name = args.name or " + ".join(args.seeds)
        args.description = args.description or (
            "Live Wikipedia link network seeded from " + ", ".join(args.seeds) +
            ". Nodes are articles, edges are real wikilinks.")
        args.source = args.source or "en.wikipedia.org (CC BY-SA 4.0)"

    if G.number_of_edges() == 0:
        sys.exit("graph has no edges")
    _write(G, args, name, args.description, args.source)


if __name__ == "__main__":
    main()
