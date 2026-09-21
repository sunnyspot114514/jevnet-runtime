from topology_experiments import _split_chunks, _overlapping_windows, GNN_NEIGHBORS


def test_split_chunks_preserves_words():
    text = "one two three four five six seven eight nine"
    chunks = _split_chunks(text, 3)
    assert " ".join(chunks) == text
    assert len(chunks) == 3


def test_windows_cover_edges():
    text = "one two three four five six seven eight nine ten eleven twelve"
    ws = _overlapping_windows(text, 3)
    assert ws[0].startswith("one")
    assert ws[-1].endswith("twelve")
    assert len(ws) == 3


def test_gnn_is_sparse_and_symmetric():
    assert len(GNN_NEIGHBORS) == 4
    for node, neighbors in GNN_NEIGHBORS.items():
        assert len(neighbors) == 2
        for n in neighbors:
            assert node in GNN_NEIGHBORS[n]
