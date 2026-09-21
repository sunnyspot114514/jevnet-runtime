import json
from pathlib import Path

import advanced_topologies as a
import packet_topology_v3 as v3


def fake_packet(o=0.0, m=0.0, t=1.0, h=0.0, c=0.0, s=1.0, r=1.0, strategy="comply"):
    return {
        "override_attempt": {"type": "noul", "noul": o},
        "meta_context": {"type": "noul", "noul": m},
        "task_observed": {"type": "noul", "noul": t},
        "substantive_harm": {"type": "score", "score": h},
        "policy_conflict": {"type": "score", "score": c},
        "safe_core_available": {"type": "noul", "noul": s},
        "decision_ready": {"type": "noul", "noul": r},
        "response_strategy": {
            "type": "choice",
            "choice": strategy,
            "probabilities": {
                "comply": float(strategy == "comply"),
                "partial_comply": float(strategy == "partial_comply"),
                "refuse": float(strategy == "refuse"),
                "escalate": float(strategy == "escalate"),
            },
        },
    }


def test_holdout_hash_is_frozen():
    raw = Path("holdout_v1.json").read_bytes()
    import hashlib
    assert hashlib.sha256(raw).hexdigest() == a.FROZEN_HOLDOUT_SHA256


def test_all_architectures_have_runner():
    assert set(a.ARCHES) == set(a.RUNNERS)


def test_frozen_guard_harm():
    p = v3.packet_snapshot(fake_packet(h=2.7, c=2.8, s=0.0, strategy="partial_comply"))
    assert a.frozen_guard(p, "partial_comply") == "refuse"


def test_frozen_guard_safe_meta():
    p = v3.packet_snapshot(fake_packet(o=0.1, m=0.95, h=0.1, c=0.1, s=0.95, strategy="partial_comply"))
    assert a.frozen_guard(p, "partial_comply") == "comply"


def test_frozen_guard_wrapper_safe_core():
    p = v3.packet_snapshot(fake_packet(o=0.95, m=0.1, h=0.1, c=0.1, s=0.95, strategy="comply"))
    assert a.frozen_guard(p, "comply") == "partial_comply"
