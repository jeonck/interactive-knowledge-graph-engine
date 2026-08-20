# Graph Engine

**Turn any network into an interactive knowledge graph — and only believe the parts that randomness cannot explain.**

Live demo: **[graph-engine.metacog.co.kr](https://graph-engine.metacog.co.kr)**

A Python engine (`networkx`) computes PageRank, HITS, betweenness, closeness and Louvain
communities, validates every score against a degree-preserving null model, and exports a single
JSON file that a dependency-free D3.js page renders as an explorable graph.

![metrics](https://img.shields.io/badge/metrics-PageRank%20%7C%20HITS%20%7C%20betweenness%20%7C%20Louvain-5eead4)
![validation](https://img.shields.io/badge/validation-degree--preserving%20null%20%2B%20BH--FDR-a78bfa)

## Why the null model matters

A centrality ranking on its own is not a finding. The node at the top of a PageRank table is
usually just the node with the most links — that is arithmetic, not insight.

So every score is re-computed on many *random twins* of the graph: the same nodes, the exact same
in- and out-degree for every one of them, but randomly rewired edges. The observed score becomes a
z-score against that ensemble, p-values get a Benjamini–Hochberg correction at 5% FDR, and only
what survives is labelled **significant**.

Read it as: *this node is more central than its own connection count already guarantees.*

Degree centrality deliberately has no z-score — the null model holds degree fixed, so degree can
never be surprising.

## What it answers

| Question | Metric | In the UI |
|---|---|---|
| What is the core concept here? | PageRank | ranking + `Findings` card |
| Which notes collect, which are the sources? | HITS hub / authority | directed graphs only |
| What bridges two unrelated domains? | Betweenness | bridge finding, z vs. null |
| How does this split into topics? | Louvain communities | colours, legend, modularity z |
| Is any of this real? | degree-preserving null + BH-FDR | `sig` / `n.s.` badges, `Significant only` filter |

## Quickstart

```bash
pip install -r requirements.txt

# your own data: a CSV with source,target[,weight]
python -m graphengine file examples/knowledge-base.csv --slug my-graph --name "My graph"

# a bundled classic
python -m graphengine builtin les-miserables

# a live Wikipedia link network, ranked by real pageviews
python -m graphengine wikipedia "Machine learning" "Number theory" --size 200

# then open the site
python -m http.server 8765 --directory docs
```

Each run writes `docs/data/<slug>.json` and registers it in `docs/data/index.json`, so the site
picks it up with no build step. `--rewires N` sets the size of the null ensemble (default 50; more
rewirings mean tighter z-scores and a slower run).

Use it as a library:

```python
import networkx as nx
from graphengine import analyze, to_site_json

G = nx.karate_club_graph()
result = analyze(G, rewires=100)
result["globals"]["modularity_z"]           # 10.3 — the clubs are real
result["stats"]["betweenness"]["Member 0"]  # value, null_mean, z, p, sig
```

## Demo datasets

| Dataset | Nodes | What it shows |
|---|---|---|
| Wikipedia concept network | ~250 | Live wikilinks across six seed domains; HITS and bridges on real directed data |
| Les Misérables | 77 | Textbook community structure — modularity z ≈ 32 |
| Karate club | 34 | The classic split, rediscovered without knowing the answer |
| Personal knowledge base | 25 | Too small to prove anything, and the engine says so |

## Layout

```
graphengine/engine.py     metrics, rewiring, z-scores, BH-FDR, JSON export
graphengine/datasets.py   CSV/JSON loaders, networkx classics, Wikipedia crawler (cached)
graphengine/cli.py        python -m graphengine {file,builtin,wikipedia}
docs/                     the static site: index.html + app.js + style.css + data/*.json
tests/test_engine.py      runs with pytest or plain python
```

## Method, in four lines

1. Measure PageRank, HITS, betweenness, closeness, degree and Louvain communities.
2. Rewire the graph `N` times with degree-preserving edge swaps (`nx.directed_edge_swap`).
3. z-score each observed value against its null distribution; p from the normal tail, then
   Benjamini–Hochberg at q = 0.05. The empirical count is kept alongside as `p_emp`.
4. Do the same for modularity, so the community structure has to earn its colours too.

Caveats worth knowing: the p-values are a normal approximation of the null tails (fine for
z-scores of this size, rough in the extreme tail); Louvain is stochastic and seeded; the Wikipedia
crawler ranks candidate articles by 30-day pageviews, which favours currently popular topics.

## Licence

MIT. Wikipedia content is CC BY-SA 4.0; Les Misérables and karate club data ship with `networkx`.
