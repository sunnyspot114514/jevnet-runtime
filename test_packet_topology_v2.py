from packet_topology_v2 import (
    PACKET_QUESTIONS,
    GNN_NEIGHBORS,
    preservation_metrics,
    packet_snapshot,
)


EXPECTED_FIELDS = {
    "override_attempt",
    "meta_context",
    "substantive_harm",
    "policy_conflict",
    "safe_core_available",
    "response_strategy",
}


def fake_packet(override, meta, harm, conflict, safe, strategy="comply"):
    return {
        "override_attempt": {"type": "noul", "noul": override},
        "meta_context": {"type": "noul", "noul": meta},
        "substantive_harm": {"type": "score", "score": harm},
        "policy_conflict": {"type": "score", "score": conflict},
        "safe_core_available": {"type": "noul", "noul": safe},
        "response_strategy": {
            "type": "choice",
            "choice": strategy,
            "probabilities": {
                "comply": 1.0 if strategy == "comply" else 0.0,
                "partial_comply": 1.0 if strategy == "partial_comply" else 0.0,
                "refuse": 1.0 if strategy == "refuse" else 0.0,
                "escalate": 1.0 if strategy == "escalate" else 0.0,
            },
        },
    }


def test_packet_contract_is_shared_six_channel_schema():
    assert set(PACKET_QUESTIONS) == EXPECTED_FIELDS


def test_snapshot_preserves_independent_channels():
    p = fake_packet(0.9, 0.1, 0.2, 0.4, 0.95, "partial_comply")
    s = packet_snapshot(p)
    assert s["override_p"] == 0.9
    assert s["harm"] == 0.2
    assert s["safe_core_p"] == 0.95
    assert s["strategy"] == "partial_comply"


def test_preservation_reports_loss_not_hidden_by_category():
    upstream = [fake_packet(0.9, 0.0, 2.9, 2.8, 0.0, "refuse")]
    final = fake_packet(0.7, 0.0, 1.2, 1.4, 0.2, "partial_comply")
    m = preservation_metrics(final, upstream)
    assert m["harm_delta"] < 0
    assert m["conflict_delta"] < 0
    assert m["override_delta"] < 0


def test_gnn_edges_are_symmetric_two_neighbor_graph():
    for node, neighbors in GNN_NEIGHBORS.items():
        assert len(neighbors) == 2
        for n in neighbors:
            assert node in GNN_NEIGHBORS[n]
