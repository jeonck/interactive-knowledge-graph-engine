"""Runnable with `pytest tests/` or plain `python3 tests/test_engine.py`."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import networkx as nx  # noqa: E402

from graphengine import datasets, engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_engine_self_check():
    engine.demo()


def test_directed_metrics_include_hits():
    G = nx.gnp_random_graph(30, 0.15, seed=1, directed=True)
    r = engine.analyze(G, rewires=10, seed=1)
    assert {"hub", "authority", "in_degree", "out_degree"} <= set(r["metrics"])
    assert "hub" not in engine.analyze(nx.karate_club_graph(), rewires=5)["metrics"]


def test_significance_is_not_a_rubber_stamp():
    """Nothing may be flagged on a graph whose only structure is its degrees."""
    G = nx.barabasi_albert_graph(80, 3, seed=7)  # hubs, but no communities
    r = engine.analyze(G, rewires=40, seed=7)
    flagged = sum(1 for v in G if r["stats"]["pagerank"][v].get("sig"))
    assert flagged <= 0.1 * G.number_of_nodes(), flagged


def test_csv_roundtrip_and_site_json():
    G = datasets.load_edgelist(ROOT / "examples" / "knowledge-base.csv")
    assert G.is_directed() and G.number_of_edges() > 25
    payload = engine.to_site_json(G, engine.analyze(G, rewires=10, seed=0),
                                  name="test", description="d", source="s")
    assert payload["globals"]["nodes"] == G.number_of_nodes()
    node = payload["nodes"][0]
    assert {"z", "p", "value"} <= set(node["scores"]["pagerank"])
    json.dumps(payload)  # must be serialisable for the site


def test_cli_writes_json(tmp_path=Path("/tmp/graphengine-test")):
    tmp_path.mkdir(exist_ok=True)
    out = tmp_path / "out.json"
    subprocess.run([sys.executable, "-m", "graphengine", "file",
                    str(ROOT / "examples" / "knowledge-base.csv"),
                    "--rewires", "5", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    data = json.loads(out.read_text())
    assert data["nodes"] and data["links"]


def test_site_data_is_in_sync():
    index = json.loads((ROOT / "docs/data/index.json").read_text())
    for entry in index:
        data = json.loads((ROOT / "docs/data" / entry["file"]).read_text())
        assert data["globals"]["nodes"] == entry["nodes"] == len(data["nodes"])
        ids = {n["id"] for n in data["nodes"]}
        assert all(l["source"] in ids and l["target"] in ids for l in data["links"])


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
