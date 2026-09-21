import hashlib, json
from pathlib import Path
import networkx as nx


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_large_type_graph_hash():
    assert sha("flygraph_large_controls_v1.json") == "db39bb7941fd170a0c87cde3d410b1aa26350c0a630662c4e9e924183e2e9149"


def test_body_graph_hash():
    assert sha("flygraph_body_pc1_v1.json") == "2399a3977ac282e8bdf324e16d332d5317bab2106194ad117f02bbaf6c9be0d6"


def test_body_control_hash():
    assert sha("flygraph_body_controls_v1.json") == "acedf9820fb7e51d927b024f40cdcdc4f86f43a80cbdd234b7a00e4f478cf861"


def test_body_fly_graph_is_strongly_connected():
    x=json.load(open("flygraph_body_controls_v1.json"))
    g=nx.DiGraph()
    g.add_nodes_from(x["fly"]["nodes"])
    g.add_edges_from((e["source"],e["target"]) for e in x["fly"]["edges"])
    assert nx.is_strongly_connected(g)
    assert x["readout_body"] == 13244
    assert max(nx.shortest_path_length(g,n,x["readout_body"]) for n in g) == 3


def test_degree_control_preserves_per_node_degree():
    x=json.load(open("flygraph_body_controls_v1.json"))
    assert x["fly"]["metrics"]["in_degree_sequence"] == x["rewired"]["metrics"]["in_degree_sequence"]
    assert x["fly"]["metrics"]["out_degree_sequence"] == x["rewired"]["metrics"]["out_degree_sequence"]
