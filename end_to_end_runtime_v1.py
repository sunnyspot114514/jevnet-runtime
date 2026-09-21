#!/usr/bin/env python3
"""End-to-end Jev -> durable runtime -> replicated COC integration.

Created before end_to_end_runtime_benchmark_v1.json is frozen.

Natural-language request path:
1. three Jev semantic authorizers
2. one typed Jev boundary auditor
3. deterministic authorization gate
4. Durable Authorization Record (DAR)
5. lease/fencing token
6. idempotent provider dispatch
7. duplicate recovery dispatch from second replica
8. lease handoff + stale old-owner retry
9. valid + forged observations
10. deterministic reconciliation
11. local COC candidate
12. replicated COC safety handoff (old quorum -> new quorum inherits chosen value)

Mechanical tool payloads are benchmark-provided structured receipts. Jev is not
asked to reconstruct IDs/paths/versions from prose; that design follows earlier
hybrid-parser findings.

The experiment tests composition of previously isolated invariants.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jev_authorizer_boundary_v4 as authv4
from jevnet_experiment import usage_tokens

BENCH_PATH=Path("end_to_end_runtime_benchmark_v1.json")
BENCH_SHA256="8855d8bf598cbac2b2fa35f5c7ed14f43f4f3c3358b731068e1fcf427da8537c"
RUN_ID="end-to-end-runtime-v1"
AUTHORIZERS=("A1","A2","A3")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_benchmark():
    if BENCH_SHA256=="__TO_BE_FROZEN__":
        raise SystemExit("benchmark hash not frozen")
    if sha256(BENCH_PATH)!=BENCH_SHA256:
        raise SystemExit("end-to-end benchmark hash mismatch")
    return json.loads(BENCH_PATH.read_text(encoding="utf-8"))


def proposal_hash(case):
    blob=json.dumps({
        "proposal":case["proposal"],
        "tool_payload":case["tool_payload"],
    },sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass
class Lease:
    fence:int=0
    owner:str|None=None

    def acquire(self,owner):
        self.fence+=1
        self.owner=owner
        return self.fence


@dataclass
class Provider:
    min_fence:int=0
    effects:dict[str,dict[str,Any]]=field(default_factory=dict)
    calls:int=0
    rejected:list[dict[str,Any]]=field(default_factory=list)

    def advance_fence(self,fence):
        self.min_fence=max(self.min_fence,fence)

    def dispatch(self,*,dar,fence,replica):
        self.calls+=1

        if fence < self.min_fence:
            r={"status":"REJECTED_STALE_FENCE","replica":replica,"fence":fence}
            self.rejected.append(copy.deepcopy(r))
            return r

        self.advance_fence(fence)
        idem=dar["idempotency_key"]
        if idem in self.effects:
            return copy.deepcopy(self.effects[idem])

        receipt={
            "status":"SUCCEEDED",
            "action_id":dar["action_id"],
            "auth_id":dar["auth_id"],
            "proposal_hash":dar["proposal_hash"],
            "idempotency_key":idem,
            "fence":fence,
            "result":copy.deepcopy(dar["tool_payload"]),
            "receipt_id":f"REC-{dar['action_id']}",
        }
        self.effects[idem]=receipt
        return copy.deepcopy(receipt)

    def query(self,idem):
        r=self.effects.get(idem)
        return copy.deepcopy(r) if r else None


def reconcile_observations(dar,observations):
    valid=[]
    rejected=[]

    for obs in observations:
        if obs.get("auth_id")!=dar["auth_id"]:
            rejected.append((obs.get("receipt_id"),"AUTH_MISMATCH"));continue
        if obs.get("proposal_hash")!=dar["proposal_hash"]:
            rejected.append((obs.get("receipt_id"),"PROPOSAL_HASH_MISMATCH"));continue
        if obs.get("idempotency_key")!=dar["idempotency_key"]:
            rejected.append((obs.get("receipt_id"),"IDEMPOTENCY_MISMATCH"));continue
        if obs.get("status")!="SUCCEEDED":
            rejected.append((obs.get("receipt_id"),"NON_SUCCESS"));continue
        if obs.get("result")!=dar["tool_payload"]:
            rejected.append((obs.get("receipt_id"),"RESULT_MISMATCH"));continue
        valid.append(obs)

    if not valid:
        return None,rejected

    # Stable deterministic representative.
    chosen=sorted(valid,key=lambda x:x["receipt_id"])[0]
    coc={
        "action_id":dar["action_id"],
        "auth_id":dar["auth_id"],
        "proposal_hash":dar["proposal_hash"],
        "idempotency_key":dar["idempotency_key"],
        "status":"SUCCEEDED",
        "result":chosen["result"],
        "receipt_id":chosen["receipt_id"],
    }
    coc_blob=json.dumps(coc,sort_keys=True,separators=(",",":")).encode()
    coc["coc_hash"]=hashlib.sha256(coc_blob).hexdigest()
    return coc,rejected


def replicated_coc_handoff(valid_hash):
    """3-replica single-slot handoff with one conflicting candidate.

    AB chooses valid_hash at ballot1.
    New leader C proposes FAKE at ballot2 on quorum BC.
    B carries accepted history, so safe Phase-1 must select valid_hash.
    """
    fake_hash=hashlib.sha256(b"FORGED-CONFLICTING-COC").hexdigest()

    accepted={
        "A":(1,valid_hash),
        "B":(1,valid_hash),
        "C":(0,None),
    }
    historical={valid_hash}

    # Phase1 quorum B,C.
    rows=[accepted["B"],accepted["C"]]
    highest=max(b for b,_ in rows)
    if highest>0:
        selected=next(v for b,v in rows if b==highest)
    else:
        selected=fake_hash

    accepted["B"]=(2,selected)
    accepted["C"]=(2,selected)
    historical.add(selected)

    return {
        "fake_candidate_hash":fake_hash,
        "ballot2_selected_hash":selected,
        "historical_chosen_hashes":sorted(historical),
        "safety_holds":historical=={valid_hash},
    }


def semantic_frontend(api_key,case):
    t0=time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        sem_futs=[ex.submit(authv4.semantic_vote,api_key,case,a) for a in AUTHORIZERS]
        boundary_fut=ex.submit(authv4.boundary_vote,api_key,case)
        sem=[f.result() for f in sem_futs]
        boundary=boundary_fut.result()
    wall=(time.perf_counter()-t0)*1000

    labels=[x["vote"] for x in sem]
    quorum=authv4.quorum_authorized(labels)
    authorized=quorum and boundary["boundary_decision"]=="ALLOW"

    return {
        "semantic_votes":sem,
        "labels":labels,
        "semantic_quorum":quorum,
        "boundary":boundary,
        "authorized":authorized,
        "wall_ms":wall,
    }


def run_case(api_key,case):
    front=semantic_frontend(api_key,case)
    expected=bool(case["expected_authorized"])

    result={
        "id":case["id"],
        "expected_authorized":expected,
        "frontend_authorized":front["authorized"],
        "frontend_correct":front["authorized"]==expected,
        "semantic_labels":front["labels"],
        "effect_class":front["boundary"]["effect_class"],
        "boundary_decision":front["boundary"]["boundary_decision"],
        "frontend_wall_ms":front["wall_ms"],
        "provider_effect_count":0,
        "provider_calls":0,
        "stale_rejections":0,
        "forged_observation_rejections":0,
        "coc_present":False,
        "replicated_coc_safe":True,
        "dar":None,
        "coc":None,
    }

    inp=sum(x["input_tokens"] for x in front["semantic_votes"])+front["boundary"]["input_tokens"]
    out=sum(x["output_tokens"] for x in front["semantic_votes"])+front["boundary"]["output_tokens"]
    result["input_tokens"]=inp
    result["output_tokens"]=out

    if not front["authorized"]:
        return result

    ph=proposal_hash(case)
    dar={
        "action_id":case["id"],
        "auth_id":f"AUTH-{case['id']}",
        "auth_generation":1,
        "proposal_hash":ph,
        "approvers":[a for a,v in zip(AUTHORIZERS,front["labels"]) if v=="APPROVE"],
        "effect_class":front["boundary"]["effect_class"],
        "idempotency_key":f"IDEM-{case['id']}",
        "tool_payload":case["tool_payload"],
    }
    result["dar"]=dar

    lease=Lease()
    provider=Provider()

    # R1 acquires execution lease and dispatches.
    f1=lease.acquire("R1")
    provider.advance_fence(f1)
    receipt1=provider.dispatch(dar=dar,fence=f1,replica="R1")

    # R2 independently recovers the same DAR before handoff: same idem -> same effect.
    receipt2=provider.dispatch(dar=dar,fence=f1,replica="R2")

    # Lease handoff to R2. Old R1 later retries and must be fenced.
    f2=lease.acquire("R2")
    provider.advance_fence(f2)
    stale=provider.dispatch(dar=dar,fence=f1,replica="R1-late")

    # Build one forged observation plus the valid provider receipt.
    forged=copy.deepcopy(receipt1)
    forged["auth_id"]="FORGED-AUTH"
    forged["receipt_id"]="FORGED-REC"

    valid=provider.query(dar["idempotency_key"])
    coc,rejected=reconcile_observations(dar,[forged,valid])

    result["provider_effect_count"]=len(provider.effects)
    result["provider_calls"]=provider.calls
    result["stale_rejections"]=sum(r["status"]=="REJECTED_STALE_FENCE" for r in provider.rejected)
    result["forged_observation_rejections"]=len(rejected)
    result["receipt_same_under_duplicate_recovery"]=receipt1.get("receipt_id")==receipt2.get("receipt_id")
    result["coc_present"]=coc is not None
    result["coc"]=coc

    if coc is not None:
        rep=replicated_coc_handoff(coc["coc_hash"])
        result["replicated_coc"]=rep
        result["replicated_coc_safe"]=rep["safety_holds"]

    return result


def main():
    cases=load_benchmark()
    api_key=os.environ.get("TYPESAFE_API_KEY","").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    outdir=Path("end_to_end_runtime_results")
    outdir.mkdir(exist_ok=True)
    raw=outdir/f"raw-{RUN_ID}.jsonl"
    meta=outdir/f"meta-{RUN_ID}.json"
    if raw.exists() or meta.exists():
        raise SystemExit("end-to-end run exists; refusing replay")

    rows=[]
    with raw.open("w",encoding="utf-8") as f:
        for i,case in enumerate(cases,1):
            r=run_case(api_key,case)
            rows.append(r)
            f.write(json.dumps({"case":case,"result":r},ensure_ascii=False)+"\n");f.flush()
            print(
                f"[{i:02d}/{len(cases)}] {case['id']} exp={case['expected_authorized']} "
                f"votes={r['semantic_labels']} class={r['effect_class']} "
                f"auth={r['frontend_authorized']} effect={r['provider_effect_count']} "
                f"COC={r['coc_present']} replicated_safe={r['replicated_coc_safe']}"
            )

    authorized=[r for r in rows if r["expected_authorized"]]
    denied=[r for r in rows if not r["expected_authorized"]]

    summary={
        "run_id":RUN_ID,
        "benchmark_sha256":BENCH_SHA256,
        "n_cases":len(rows),
        "frontend_accuracy":statistics.mean(r["frontend_correct"] for r in rows),
        "authorized_case_count":len(authorized),
        "denied_case_count":len(denied),
        "authorized_exactly_one_effect_rate":statistics.mean(r["provider_effect_count"]==1 for r in authorized),
        "authorized_coc_rate":statistics.mean(r["coc_present"] for r in authorized),
        "authorized_replicated_coc_safety_rate":statistics.mean(r["replicated_coc_safe"] for r in authorized),
        "denied_zero_effect_rate":statistics.mean(r["provider_effect_count"]==0 for r in denied),
        "denied_zero_coc_rate":statistics.mean(not r["coc_present"] for r in denied),
        "duplicate_recovery_same_receipt_rate":statistics.mean(r.get("receipt_same_under_duplicate_recovery",False) for r in authorized),
        "stale_retry_rejected_rate":statistics.mean(r["stale_rejections"]>=1 for r in authorized),
        "forged_observation_rejected_rate":statistics.mean(r["forged_observation_rejections"]>=1 for r in authorized),
        "mean_frontend_wall_ms":statistics.mean(r["frontend_wall_ms"] for r in rows),
        "mean_input_tokens":statistics.mean(r["input_tokens"] for r in rows),
        "wrong_ids":[r["id"] for r in rows if not r["frontend_correct"]],
    }
    meta.write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
