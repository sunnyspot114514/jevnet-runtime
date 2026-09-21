#!/usr/bin/env python3
"""Post-hoc diagnostic on known v2 authorizer errors.

NOT a confirmatory benchmark.

Re-evaluates only:
- B26 chmod permission-change correlated error
- B29 ambiguous database target
- B31 ambiguous shared-folder target

using the heterogeneous H1/H2/H3 prompts defined before v3.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import jev_authorizer_quorum_v3 as v3

V2=Path("jev_authorizer_benchmark_v2.json")
TARGETS={"B26","B29","B31"}


def main():
    api_key=os.environ.get("TYPESAFE_API_KEY","").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    cases=[c for c in json.loads(V2.read_text(encoding="utf-8")) if c["id"] in TARGETS]
    out=[]

    for case in cases:
        r=v3.run_mode(api_key,case,"heterogeneous")
        row={
            "id":case["id"],
            "proposal":case["proposal"],
            "expected_decision":case["expected_decision"],
            "labels":r["labels"],
            "majority_label":r["majority_label"],
            "quorum_authorized":r["quorum_authorized"],
            "expected_authorized":case["expected_authorized"],
            "votes":[
                {
                    "voter_id":x["voter_id"],
                    "vote":x["vote"],
                    "probabilities":x["probabilities"],
                }
                for x in r["votes"]
            ],
        }
        out.append(row)
        print("\n",case["id"],case["proposal"])
        print("expected",case["expected_decision"])
        for x in row["votes"]:
            print(x["voter_id"],x["vote"],x["probabilities"])
        print("majority",row["majority_label"],"auth",row["quorum_authorized"])

    Path("authorizer_v2_hetero_posthoc.json").write_text(
        json.dumps(out,indent=2,ensure_ascii=False),encoding="utf-8"
    )


if __name__=="__main__":
    main()
