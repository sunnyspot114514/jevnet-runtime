#!/usr/bin/env python3
"""Post-hoc: apply v4 typed boundary veto to known v2 chmod failure.

Not confirmatory evidence. This only tests whether the architectural mechanism
can contain the already-known correlated error.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import jev_authorizer_boundary_v4 as v4

TARGET="B26"


def main():
    api_key=os.environ.get("TYPESAFE_API_KEY","").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    cases=json.loads(Path("jev_authorizer_benchmark_v2.json").read_text(encoding="utf-8"))
    case=next(c for c in cases if c["id"]==TARGET)

    b=v4.boundary_vote(api_key,case)
    result={
        "id":TARGET,
        "proposal":case["proposal"],
        "known_v2_semantic_votes":["APPROVE","APPROVE","APPROVE"],
        "known_v2_semantic_quorum_authorized":True,
        "typed_boundary_effect_class":b["effect_class"],
        "typed_boundary_decision":b["boundary_decision"],
        "typed_boundary_probabilities":b["probabilities"],
        "quorum_plus_veto_authorized":(
            True and b["boundary_decision"]=="ALLOW"
        ),
        "status":"post-hoc mechanism diagnostic; not a fresh benchmark",
    }
    print(json.dumps(result,indent=2))
    Path("authorizer_b26_boundary_veto_posthoc.json").write_text(
        json.dumps(result,indent=2),encoding="utf-8"
    )


if __name__=="__main__":
    main()
