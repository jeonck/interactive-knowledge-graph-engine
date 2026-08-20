"""Network metrics + randomness validation.

The point of this module: a raw centrality score is not evidence. A node can
top the PageRank ranking simply because it has many links. So every score is
compared against a null ensemble of degree-preserving random rewirings of the
same graph. What survives is a pattern that degree alone does not explain.
"""

from __future__ import annotations

import math
import random
from statistics import mean, pstdev

import networkx as nx

# Metrics validated against the null model. Degree is deliberately absent:
# the null preserves every node's degree, so its z-score is 0 by construction.
VALIDATED = ("pagerank", "authority", "hub", "betweenness", "closeness")
ALL_METRICS = ("pagerank", "authority", "hub", "betweenness", "closeness",
               "degree", "in_degree", "out_degree")
FDR_Q = 0.05


def compute_metrics(G, weight="weight"):
    """Raw scores for every metric, as {metric: {node: value}}."""
    und = G.to_undirected(as_view=False) if G.is_directed() else G
    n = G.number_of_nodes()
    scale = 1.0 / (n - 1) if n > 1 else 1.0
    out = {
        "pagerank": nx.pagerank(G, weight=weight),
        "betweenness": nx.betweenness_centrality(G, normalized=True),
        # distance = 1/weight: heavier link means the two nodes are closer
        "closeness": nx.closeness_centrality(und, distance=None),
        "degree": {v: d * scale for v, d in G.degree()},
    }
    if G.is_directed():
        # HITS only says something new when links have a direction; on an
        # undirected graph hub and authority collapse to the same score.
        out["hub"], out["authority"] = nx.hits(G, max_iter=500, normalized=True)
        out["in_degree"] = {v: d * scale for v, d in G.in_degree()}
        out["out_degree"] = {v: d * scale for v, d in G.out_degree()}
    return out


def rewire(G, rng):
    """A degree-preserving random twin of G (configuration-model style)."""
    H = G.copy()
    H.remove_edges_from(nx.selfloop_edges(H))
    m = H.number_of_edges()
    if m < 2 or H.number_of_nodes() < 4:
        return H
    swaps = max(1, 10 * m)
    try:
        if H.is_directed():
            nx.directed_edge_swap(H, nswap=swaps, max_tries=swaps * 20, seed=rng)
        else:
            nx.double_edge_swap(H, nswap=swaps, max_tries=swaps * 20, seed=rng)
    except (nx.NetworkXError, nx.NetworkXAlgorithmError):
        pass  # too constrained to rewire fully; partial shuffle is still a null
    return H


def communities(G, seed=0):
    und = nx.Graph(G.to_undirected() if G.is_directed() else G)
    parts = nx.community.louvain_communities(und, seed=seed)
    parts = sorted(parts, key=len, reverse=True)
    label = {v: i for i, part in enumerate(parts) for v in part}
    return label, nx.community.modularity(und, parts)


def _bh_significant(pvals, q=FDR_Q):
    """Benjamini-Hochberg: which p-values survive at FDR q. Returns a set of keys."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    n = len(items)
    cutoff = 0.0
    for i, (_, p) in enumerate(items, start=1):
        if p <= i / n * q:
            cutoff = p
    return {k for k, p in items if p <= cutoff and cutoff > 0}


def analyze(G, rewires=50, seed=0, weight="weight", progress=None):
    """Metrics + null-model z-scores/p-values + communities. Returns a dict."""
    rng = random.Random(seed)
    obs = compute_metrics(G, weight=weight)
    comm, modularity = communities(G, seed=seed)

    validated = [m for m in VALIDATED if m in obs]
    null = {m: {v: [] for v in G} for m in validated}
    null_mod = []
    for i in range(rewires):
        H = rewire(G, rng)
        h_obs = compute_metrics(H, weight=weight)
        for m in validated:
            for v, val in h_obs[m].items():
                null[m][v].append(val)
        null_mod.append(communities(H, seed=seed)[1])
        if progress:
            progress(i + 1, rewires)

    stats = {}
    for m in validated:
        pv = {}
        stats[m] = {}
        for v in G:
            samples = null[m][v]
            mu, sd = (mean(samples), pstdev(samples)) if samples else (0.0, 0.0)
            z = (obs[m][v] - mu) / sd if sd > 1e-12 else 0.0
            # Empirical p is bounded below by 1/(rewires+1), too coarse for an
            # FDR correction over hundreds of nodes, so the reported p is the
            # right-tail normal approximation of the z-score; the empirical
            # count is kept alongside it as a sanity check.
            p = 0.5 * math.erfc(z / math.sqrt(2))
            p_emp = (1 + sum(1 for s in samples if s >= obs[m][v])) / (len(samples) + 1) if samples else 1.0
            stats[m][v] = {"value": obs[m][v], "null_mean": mu, "z": z, "p": p, "p_emp": p_emp}
            pv[v] = p
        for v in _bh_significant(pv):
            stats[m][v]["sig"] = True

    mu, sd = (mean(null_mod), pstdev(null_mod)) if null_mod else (0.0, 0.0)
    globals_ = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "directed": G.is_directed(),
        "density": nx.density(G),
        "modularity": modularity,
        "modularity_null_mean": mu,
        "modularity_z": (modularity - mu) / sd if sd > 1e-12 else 0.0,
        "communities": len(set(comm.values())),
        "rewires": rewires,
        "fdr_q": FDR_Q,
    }
    return {"raw": obs, "stats": stats, "community": comm,
            "globals": globals_, "metrics": [m for m in ALL_METRICS if m in obs]}


def to_site_json(G, result, name, description="", source=""):
    """Flatten an analyze() result into the JSON the D3 front-end reads."""
    raw, stats, comm = result["raw"], result["stats"], result["community"]
    nodes = []
    for v in G:
        scores = {}
        for m in result["metrics"]:
            s = stats.get(m, {}).get(v)
            entry = {"value": round(raw[m][v], 6)}
            if s:
                entry.update(z=round(s["z"], 3), p=s["p"], p_emp=round(s["p_emp"], 4),
                             null_mean=round(s["null_mean"], 6), sig=bool(s.get("sig")))
            scores[m] = entry
        nodes.append({"id": str(v), "label": str(v), "community": comm[v],
                      "degree": G.degree(v), "scores": scores})
    links = [{"source": str(u), "target": str(w), "weight": float(d.get("weight", 1))}
             for u, w, d in G.edges(data=True)]
    g = dict(result["globals"])
    g["density"] = round(g["density"], 5)
    for k in ("modularity", "modularity_null_mean", "modularity_z"):
        g[k] = round(g[k], 4)
    return {"name": name, "description": description, "source": source,
            "globals": g, "metrics": result["metrics"], "nodes": nodes, "links": links}


def demo():
    """Self-check: the engine must find planted structure and reject noise."""
    G = nx.karate_club_graph()
    r = analyze(G, rewires=20, seed=1)
    assert r["globals"]["communities"] >= 2
    assert r["globals"]["modularity_z"] > 2, r["globals"]  # real clubs beat rewired ones
    top = max(r["raw"]["pagerank"], key=r["raw"]["pagerank"].get)
    assert top in (0, 33), top  # the instructor and the club president
    assert any(r["stats"]["betweenness"][v].get("sig") for v in G)  # structure is found

    # A pure Erdos-Renyi graph has no structure beyond degree: almost nothing
    # should pass the FDR filter.
    R = nx.gnm_random_graph(60, 240, seed=3)
    rr = analyze(R, rewires=30, seed=2)
    flagged = sum(1 for v in R if rr["stats"]["betweenness"][v].get("sig"))
    assert flagged <= 0.1 * R.number_of_nodes(), flagged
    assert abs(rr["globals"]["modularity_z"]) < 8

    # Bridge detection: two dense blobs joined by one node.
    B = nx.Graph()
    B.add_edges_from((f"a{i}", f"a{j}") for i in range(8) for j in range(i + 1, 8))
    B.add_edges_from((f"b{i}", f"b{j}") for i in range(8) for j in range(i + 1, 8))
    B.add_edges_from([("a0", "bridge"), ("b0", "bridge")])
    br = analyze(B, rewires=30, seed=4)
    assert max(br["raw"]["betweenness"], key=br["raw"]["betweenness"].get) == "bridge"
    print("engine demo OK", r["globals"]["modularity_z"], flagged)


if __name__ == "__main__":
    demo()
