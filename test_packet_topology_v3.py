from packet_topology_v3 import (
    PACKET_QUESTIONS,
    channel_extrema,
    packet_snapshot,
)


EXPECTED_FIELDS = {
    "override_attempt",
    "meta_context",
    "task_observed",
    "substantive_harm",
    "policy_conflict",
    "safe_core_available",
    "decision_ready",
    "response_strategy",
}


def fake_packet(
    override=0.0,
    meta=0.0,
    observed=1.0,
    harm=0.0,
    conflict=0.0,
    safe=1.0,
    ready=1.0,
    strategy="comply",
):
    return {
        "override_attempt": {"type": "noul", "noul": override},
        "meta_context": {"type": "noul", "noul": meta},
        "task_observed": {"type": "noul", "noul": observed},
        "substantive_harm": {"type": "score", "score": harm},
        "policy_conflict": {"type": "score", "score": conflict},
        "safe_core_available": {"type": "noul", "noul": safe},
        "decision_ready": {"type": "noul", "noul": ready},
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


def test_v3_packet_contract_has_scope_and_readiness():
    assert set(PACKET_QUESTIONS) == EXPECTED_FIELDS


def test_snapshot_exposes_scope_and_readiness():
    s = packet_snapshot(fake_packet(observed=0.25, ready=0.15))
    assert s["task_observed_p"] == 0.25
    assert s["decision_ready_p"] == 0.15


def test_extrema_ignore_harm_from_unobserved_task():
    wrapper_only = fake_packet(observed=0.1, harm=2.9, conflict=2.9, override=0.95, ready=0.1)
    concrete = fake_packet(observed=0.95, harm=0.2, conflict=0.1, override=0.2, ready=0.8)
    e = channel_extrema([wrapper_only, concrete])
    assert e["max_concrete_harm"] == 0.2
    assert e["max_concrete_conflict"] == 0.1
    assert e["max_override_p"] == 0.95
    assert e["max_decision_ready_p"] == 0.8


def test_extrema_preserve_high_concrete_harm():
    benign = fake_packet(observed=1.0, harm=0.1, conflict=0.1)
    harmful = fake_packet(observed=1.0, harm=2.8, conflict=2.9, safe=0.0, strategy="refuse")
    e = channel_extrema([benign, harmful])
    assert e["max_concrete_harm"] == 2.8
    assert e["max_concrete_conflict"] == 2.9
