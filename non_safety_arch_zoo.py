#!/usr/bin/env python3
"""Exploratory non-safety architecture zoo on frozen benchmark v1.

Uses the same slot packet contract as flygraph_benchmark.py.
Architectures:
- mlp_dense
- rnn_residual
- transformer1
- moe

This is post-hoc exploratory on benchmark v1. Any promising result requires a
fresh benchmark v2 for confirmation.
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import flygraph_benchmark as fb
from jevnet_experiment import post_jev, choice_probs, winner, usage_tokens

ARCHES = ("mlp_dense", "rnn_residual", "transformer1", "moe")


def usage(responses):
    i=o=0
    for r in responses:
        a,b=usage_tokens(r); i+=a; o+=b
    return i,o


def finish(task, responses, final_packet, wall, times, trace):
    inp,out=usage(responses)
    return {
        "choice": fb.answer_choice(final_packet),
        "expected_p": fb.answer_prob(final_packet, task["expected"]),
        "slot_accuracy": fb.slot_accuracy(final_packet, [str(v) for v in task["slot_values"]]),
        "slot_known": fb.slot_known(final_packet),
        "decision_ready": float(final_packet["decision_ready"].get("noul",0)),
        "calls": len(responses),
        "critical_path_ms": wall,
        "sum_call_ms": sum(times),
        "input_tokens": inp,
        "output_tokens": out,
        "trace": trace,
    }


def call(api_key,state,q,retries,timeout):
    return post_jev(api_key,state,q,retries=retries,timeout=timeout)


def run_mlp(api_key, task, retries, timeout):
    q=fb.make_questions(task); responses=[]; times=[]; t0=time.perf_counter()
    groups=((1,2),(3,4),(5,6))

    def l1(item):
        idx,slots=item
        state={
            "node_scope":"nonsafety_mlp_local_pair",
            "task_question":task["question"],
            "local_slots":{f"slot_{s}":str(task["slot_values"][s-1]) for s in slots},
            "contract_note":"Only these two local source slots are directly observed."
        }
        r,ms=call(api_key,state,q,retries,timeout); return idx,r,ms

    with ThreadPoolExecutor(max_workers=3) as ex:
        r1=list(ex.map(l1,list(enumerate(groups))))
    responses += [r for _,r,_ in r1]; times += [ms for _,_,ms in r1]
    p1={f"l1_{i}":fb.packet(r) for i,r,_ in r1}

    def l2(idx):
        state={
            "node_scope":"nonsafety_mlp_dense_hidden",
            "task_question":task["question"],
            "node_index":idx,
            "upstream_packets":p1,
            "contract_note":"Dense hidden node: merge slot evidence by provenance; never double-count repeated copies."
        }
        r,ms=call(api_key,state,q,retries,timeout); return idx,r,ms

    with ThreadPoolExecutor(max_workers=3) as ex:
        r2=list(ex.map(l2,range(3)))
    responses += [r for _,r,_ in r2]; times += [ms for _,_,ms in r2]
    p2={f"l2_{i}":fb.packet(r) for i,r,_ in r2}

    fr,fms=call(api_key,{
        "node_scope":"nonsafety_mlp_readout",
        "task_question":task["question"],
        "upstream_packets":p2,
        "contract_note":"Final dense readout over the three hidden packets."
    },q,retries,timeout)
    responses.append(fr);times.append(fms)
    wall=(time.perf_counter()-t0)*1000
    return finish(task,responses,fb.packet(fr),wall,times,{"l1":r1,"l2":r2,"final":fr})


def run_rnn(api_key, task, retries, timeout):
    q=fb.make_questions(task); responses=[];times=[];hidden=None;seen={};t0=time.perf_counter()
    for i,value in enumerate(task["slot_values"],1):
        seen[f"slot_{i}"]=str(value)
        state={
            "node_scope":"nonsafety_rnn_residual_update",
            "step":i,
            "task_question":task["question"],
            "current_slot_index":i,
            "current_slot_value":str(value),
            "cumulative_raw_slots":dict(seen),
            "contract_note":"Use previous packet as state and cumulative_raw_slots as lossless residual memory."
        }
        if hidden is not None: state["previous_packet"]=hidden
        r,ms=call(api_key,state,q,retries,timeout)
        responses.append(r);times.append(ms);hidden=fb.packet(r)
    fr,fms=call(api_key,{
        "node_scope":"nonsafety_rnn_readout",
        "task_question":task["question"],
        "final_hidden_packet":hidden,
        "cumulative_raw_slots":seen
    },q,retries,timeout)
    responses.append(fr);times.append(fms)
    wall=(time.perf_counter()-t0)*1000
    return finish(task,responses,fb.packet(fr),wall,times,{"steps":responses[:-1],"final":fr})


def run_transformer(api_key, task, retries, timeout):
    q=fb.make_questions(task);responses=[];times=[];t0=time.perf_counter()

    def enc(i):
        state={
            "node_scope":"nonsafety_transformer_token_init",
            "position":i,
            "task_question":task["question"],
            "local_slot_index":i+1,
            "local_slot_value":str(task["slot_values"][i]),
            "contract_note":"Only this token's source slot is directly observed."
        }
        r,ms=call(api_key,state,q,retries,timeout);return i,r,ms

    with ThreadPoolExecutor(max_workers=6) as ex:
        init=list(ex.map(enc,range(6)))
    responses += [r for _,r,_ in init];times += [ms for _,_,ms in init]
    packets=[fb.packet(r) for _,r,_ in sorted(init)]

    def attn(i):
        state={
            "node_scope":"nonsafety_transformer_self_attention",
            "position":i,
            "task_question":task["question"],
            "self_packet_residual":packets[i],
            "all_token_packets":{f"token_{j+1}":p for j,p in enumerate(packets)},
            "contract_note":"All-to-all packet update. Preserve source-slot provenance and do not double-count repeated evidence."
        }
        r,ms=call(api_key,state,q,retries,timeout);return i,r,ms

    with ThreadPoolExecutor(max_workers=6) as ex:
        upd=list(ex.map(attn,range(6)))
    responses += [r for _,r,_ in upd];times += [ms for _,_,ms in upd]
    p2=[fb.packet(r) for _,r,_ in sorted(upd)]

    fr,fms=call(api_key,{
        "node_scope":"nonsafety_transformer_readout",
        "task_question":task["question"],
        "final_token_packets":{f"token_{i+1}":p for i,p in enumerate(p2)},
        "contract_note":"CLS-style readout over final token packets. No raw source-slot values are available here."
    },q,retries,timeout)
    responses.append(fr);times.append(fms)
    wall=(time.perf_counter()-t0)*1000
    return finish(task,responses,fb.packet(fr),wall,times,{"init":init,"updated":upd,"final":fr})


EXPERTS={
    "aggregation":"Set/count/frequency aggregation expert.",
    "arithmetic_sequence":"Arithmetic and ordered state-update expert.",
    "retrieval":"Key/value lookup and exact retrieval expert.",
    "graph_logic":"Graph reachability, motif, and propositional-logic expert."
}
ROUTER={
    "route":{
        "type":"choice",
        "instructions":"Choose the expert most relevant to task_question. This is routing, not the final answer.",
        "criteria":EXPERTS
    }
}


def run_moe(api_key,task,retries,timeout):
    q=fb.make_questions(task);responses=[];times=[];t0=time.perf_counter()
    allslots={f"slot_{i+1}":str(v) for i,v in enumerate(task["slot_values"])}
    rr,rms=post_jev(api_key,{
        "node_scope":"nonsafety_moe_router",
        "task_question":task["question"]
    },ROUTER,retries=retries,timeout=timeout)
    responses.append(rr);times.append(rms)
    probs=choice_probs(rr["answers"]["route"])
    top2=sorted(EXPERTS,key=lambda k:probs.get(k,0),reverse=True)[:2]

    def expert(name):
        state={
            "node_scope":"nonsafety_moe_expert",
            "expert":name,
            "expert_focus":EXPERTS[name],
            "task_question":task["question"],
            "all_source_slots":allslots,
            "router_probability":probs.get(name,0),
            "contract_note":"All source slots are visible to the selected expert; emit the common slot packet and solve within your specialty."
        }
        r,ms=call(api_key,state,q,retries,timeout);return name,r,ms

    with ThreadPoolExecutor(max_workers=2) as ex:
        ers=list(ex.map(expert,top2))
    responses += [r for _,r,_ in ers];times += [ms for _,_,ms in ers]
    ep={n:fb.packet(r) for n,r,_ in ers}

    fr,fms=call(api_key,{
        "node_scope":"nonsafety_moe_readout",
        "task_question":task["question"],
        "router_probabilities":probs,
        "selected_experts":top2,
        "expert_packets":ep,
        "contract_note":"Fuse top-2 expert packets; routing probability is relevance, not truth."
    },q,retries,timeout)
    responses.append(fr);times.append(fms)
    wall=(time.perf_counter()-t0)*1000
    return finish(task,responses,fb.packet(fr),wall,times,{"router":rr,"top2":top2,"experts":ers,"final":fr})


RUNNERS={"mlp_dense":run_mlp,"rnn_residual":run_rnn,"transformer1":run_transformer,"moe":run_moe}


def main():
    api_key=os.environ.get("TYPESAFE_API_KEY","").strip()
    if not api_key: raise SystemExit("TYPESAFE_API_KEY not set")
    tasks=fb.load_benchmark()
    outdir=Path("non_safety_arch_results");outdir.mkdir(exist_ok=True)
    run_id="nonsafety-arch-zoo-v1"
    raw=outdir/f"raw-{run_id}.jsonl";csvp=outdir/f"summary-{run_id}.csv";meta=outdir/f"meta-{run_id}.json"
    if any(p.exists() for p in (raw,csvp,meta)): raise SystemExit("run exists; refusing replay")
    items=[(t,a) for t in tasks for a in ARCHES]
    rows=[]
    with raw.open("w",encoding="utf-8") as f:
        for idx,(task,arch) in enumerate(items,1):
            res=RUNNERS[arch](api_key,task,4,60)
            f.write(json.dumps({"task":task,"arch":arch,**res},ensure_ascii=False)+"\n");f.flush()
            row={
                "id":task["id"],"category":task["category"],"expected":task["expected"],"arch":arch,
                "choice":res["choice"],"correct":int(res["choice"]==task["expected"]),
                "expected_p":res["expected_p"],"slot_accuracy":res["slot_accuracy"],"slot_known":res["slot_known"],
                "decision_ready":res["decision_ready"],"calls":res["calls"],
                "critical_path_ms":round(res["critical_path_ms"],1),"input_tokens":res["input_tokens"]
            }
            rows.append(row)
            print(f"[{idx:02d}/{len(items)}] {task['id']} {arch:12s} exp={task['expected']:8s} got={str(res['choice']):8s} P={res['expected_p']:.2f} slots={res['slot_known']}/6 acc={res['slot_accuracy']:.2f} ms={res['critical_path_ms']:.0f}")
    with csvp.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows)
    summary={}
    for arch in ARCHES:
        rs=[r for r in rows if r["arch"]==arch]
        summary[arch]={
            "accuracy":statistics.mean(r["correct"] for r in rs),
            "mean_expected_p":statistics.mean(r["expected_p"] for r in rs),
            "mean_slot_accuracy":statistics.mean(r["slot_accuracy"] for r in rs),
            "mean_slots_known":statistics.mean(r["slot_known"] for r in rs),
            "mean_ready":statistics.mean(r["decision_ready"] for r in rs),
            "mean_calls":statistics.mean(r["calls"] for r in rs),
            "mean_ms":statistics.mean(r["critical_path_ms"] for r in rs),
            "mean_input_tokens":statistics.mean(r["input_tokens"] for r in rs)
        }
    meta.write_text(json.dumps({"run_id":run_id,"benchmark_sha256":fb.BENCH_SHA256,"summary":summary},indent=2),encoding="utf-8")
    print("\n=== SUMMARY ===")
    for a,s in summary.items():
        print(f"{a:12s} acc={s['accuracy']:.3f} P={s['mean_expected_p']:.3f} slotacc={s['mean_slot_accuracy']:.3f} known={s['mean_slots_known']:.2f}/6 ready={s['mean_ready']:.2f} calls={s['mean_calls']:.1f} ms={s['mean_ms']:.0f} input={s['mean_input_tokens']:.0f}")


if __name__=="__main__":
    main()
