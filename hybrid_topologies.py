#!/usr/bin/env python3
"""Hybrid Jev topology experiments.

Architectures are defined before holdout_v2 is frozen:
- transformer_moe: chunk packets -> self-attention block -> sparse MoE experts -> readout
- transformer_global_skip: chunk packets -> self-attention block + full-context packet skip -> readout

The script later verifies a frozen holdout_v2 hash before any API call.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import advanced_topologies as adv
import packet_topology_v3 as v3
from jevnet_experiment import POLICY, MODEL, API_URL, choice_probs


HOLDOUT_PATH = Path("holdout_v2.json")
FROZEN_HOLDOUT_SHA256 = "92c78ed4dd6dc64a32bb3f72ea5a7094dc3f0a7bdcc04620fab0b2d7f319e087"

ARCHES = (
    "direct_v3",
    "transformer1",
    "transformer2",
    "encoder_decoder",
    "moe",
    "transformer_moe",
    "transformer_global_skip",
)


def normalize_case(case):
    return {
        "id": case["id"],
        "cell": case.get("category", "holdout_v2"),
        "expected": case["expected"],
        "message": case["message"],
    }


def packet_call(api_key, state, retries, timeout):
    return v3.packet_call(api_key, state, retries, timeout)


def finish(case, responses, final_resp, wall, times, upstream, trace):
    return v3.finish(normalize_case(case), responses, final_resp, wall, times, upstream, trace)


def run_existing(name, api_key, case, retries, timeout):
    return adv.RUNNERS[name](api_key, case, retries, timeout)


def run_transformer_moe(api_key, case, retries, timeout):
    responses = []
    times = []
    t0 = time.perf_counter()

    chunks, enc = adv.chunk_encode(api_key, case, retries, timeout, scope="hybrid_transformer_token_encode")
    responses.extend(r for _, r, _ in enc)
    times.extend(ms for _, _, ms in enc)
    packets = [v3.packet(r) for _, r, _ in enc]

    upd = adv.transformer_block(api_key, 1, packets, chunks, retries, timeout)
    responses.extend(r for _, r, _ in upd)
    times.extend(ms for _, _, ms in upd)
    updated_packets = [v3.packet(r) for _, r, _ in upd]

    router_state = {
        "assistant_policy": POLICY,
        "user_message": case["message"],
        "node_scope": "transformer_moe_router",
        "transformer_packets": {f"token_{i}": p for i, p in enumerate(updated_packets)},
        "token_extrema": v3.channel_extrema(updated_packets),
        "contract_note": (
            "Route based on both the original request and the self-attended packet sequence. "
            "Routing relevance is not itself a final response decision."
        ),
    }
    router_resp, router_ms = v3.post_jev(
        api_key, router_state, adv.ROUTER_QUESTION, retries=retries, timeout=timeout
    )
    responses.append(router_resp)
    times.append(router_ms)
    route_ans = router_resp["answers"]["expert_route"]
    route_probs = choice_probs(route_ans)
    top2 = sorted(adv.MOE_EXPERTS, key=lambda k: route_probs.get(k, 0.0), reverse=True)[:2]

    def expert(name):
        state = {
            "assistant_policy": POLICY,
            "user_message": case["message"],
            "node_scope": "transformer_moe_expert",
            "expert_name": name,
            "expert_focus": adv.MOE_EXPERTS[name],
            "router_probability": route_probs.get(name, 0.0),
            "transformer_packets": {f"token_{i}": p for i, p in enumerate(updated_packets)},
            "token_extrema": v3.channel_extrema(updated_packets),
            "contract_note": (
                "Use the original request as semantic ground truth context and the Transformer packets as "
                "structured auxiliary evidence. Do not inherit a packet error merely because attention repeated it."
            ),
        }
        resp, ms = packet_call(api_key, state, retries, timeout)
        return name, resp, ms

    with ThreadPoolExecutor(max_workers=2) as ex:
        ers = list(ex.map(expert, top2))
    expert_map = {n: r for n, r, _ in ers}
    responses.extend(r for _, r, _ in ers)
    times.extend(ms for _, _, ms in ers)
    expert_packets = [v3.packet(r) for _, r, _ in ers]

    final_state = {
        "assistant_policy": POLICY,
        "node_scope": "transformer_moe_readout",
        "router_probabilities": route_probs,
        "selected_experts": top2,
        "expert_packets": {n: v3.packet(r) for n, r in expert_map.items()},
        "transformer_packets": {f"token_{i}": p for i, p in enumerate(updated_packets)},
        "expert_extrema": v3.channel_extrema(expert_packets),
        "full_context_residual": case["message"],
        "contract_note": (
            "Fuse sparse experts with the self-attended representation. Prefer expert/full-context corrections "
            "when Transformer packets disagree due to local quotation or wrapper aliasing."
        ),
    }
    final_resp, final_ms = packet_call(api_key, final_state, retries, timeout)
    responses.append(final_resp)
    times.append(final_ms)
    wall = (time.perf_counter() - t0) * 1000

    return finish(
        case,
        responses,
        final_resp,
        wall,
        times,
        updated_packets + expert_packets,
        {
            "chunks": chunks,
            "encoded": [r for _, r, _ in enc],
            "transformer_block": [r for _, r, _ in upd],
            "router": router_resp,
            "top2": top2,
            "experts": expert_map,
            "final": final_resp,
        },
    )


def run_transformer_global_skip(api_key, case, retries, timeout):
    responses = []
    times = []
    t0 = time.perf_counter()

    # A full-context packet is the global residual token.
    global_resp, global_ms = packet_call(
        api_key,
        {
            "assistant_policy": POLICY,
            "user_message": case["message"],
            "node_scope": "global_residual_token",
            "contract_note": "Encode the full request into one V3 packet for use as a semantic skip connection.",
        },
        retries,
        timeout,
    )
    responses.append(global_resp)
    times.append(global_ms)
    global_packet = v3.packet(global_resp)

    chunks, enc = adv.chunk_encode(api_key, case, retries, timeout, scope="skip_transformer_token_encode")
    responses.extend(r for _, r, _ in enc)
    times.extend(ms for _, _, ms in enc)
    packets = [v3.packet(r) for _, r, _ in enc]

    upd = adv.transformer_block(api_key, 1, packets, chunks, retries, timeout)
    responses.extend(r for _, r, _ in upd)
    times.extend(ms for _, _, ms in upd)
    updated_packets = [v3.packet(r) for _, r, _ in upd]

    final_state = {
        "assistant_policy": POLICY,
        "node_scope": "transformer_global_skip_readout",
        "global_residual_packet": global_packet,
        "transformer_packets": {f"token_{i}": p for i, p in enumerate(updated_packets)},
        "token_extrema": v3.channel_extrema(updated_packets),
        "full_context_residual": case["message"],
        "contract_note": (
            "The global residual packet is an explicit semantic skip connection. Use Transformer packets for "
            "distributed evidence, but do not let repeated local errors overwrite a coherent full-context residual."
        ),
    }
    final_resp, final_ms = packet_call(api_key, final_state, retries, timeout)
    responses.append(final_resp)
    times.append(final_ms)
    wall = (time.perf_counter() - t0) * 1000

    return finish(
        case,
        responses,
        final_resp,
        wall,
        times,
        [global_packet] + updated_packets,
        {
            "global_residual": global_resp,
            "chunks": chunks,
            "encoded": [r for _, r, _ in enc],
            "transformer_block": [r for _, r, _ in upd],
            "final": final_resp,
        },
    )


RUNNERS = {
    "direct_v3": lambda a, c, r, t: run_existing("direct_v3", a, c, r, t),
    "transformer1": lambda a, c, r, t: run_existing("transformer1", a, c, r, t),
    "transformer2": lambda a, c, r, t: run_existing("transformer2", a, c, r, t),
    "encoder_decoder": lambda a, c, r, t: run_existing("encoder_decoder", a, c, r, t),
    "moe": lambda a, c, r, t: run_existing("moe", a, c, r, t),
    "transformer_moe": run_transformer_moe,
    "transformer_global_skip": run_transformer_global_skip,
}


def frozen_guard(p, jev_choice):
    return adv.frozen_guard(p, jev_choice)


def load_holdout():
    raw = HOLDOUT_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if FROZEN_HOLDOUT_SHA256 == "__TO_BE_FROZEN__":
        raise SystemExit("Holdout v2 hash has not been frozen into the script yet.")
    if digest != FROZEN_HOLDOUT_SHA256:
        raise SystemExit(f"holdout_v2 hash mismatch: {digest}")
    return json.loads(raw.decode("utf-8"))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--arch", action="append", choices=ARCHES, default=[])
    p.add_argument("--run-id", required=True)
    p.add_argument("--output-dir", default="hybrid_topology_results")
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    arches = args.arch or list(ARCHES)
    holdout = load_holdout()

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    raw_path = outdir / f"raw-{args.run_id}.jsonl"
    csv_path = outdir / f"summary-{args.run_id}.csv"
    meta_path = outdir / f"meta-{args.run_id}.json"
    if any(p.exists() for p in (raw_path, csv_path, meta_path)):
        raise SystemExit(f"Run id '{args.run_id}' already exists; refusing replay.")

    items = [(case, arch) for case in holdout for arch in arches]
    print(f"Hybrid topology holdout v2 | cases={len(holdout)} | arches={','.join(arches)} | items={len(items)}")
    if args.dry_run:
        for case, arch in items:
            print(case["id"], arch, case["expected"])
        return

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY is not set.")

    rows = []
    with raw_path.open("w", encoding="utf-8") as rawf:
        for i, (case, arch) in enumerate(items, 1):
            result = RUNNERS[arch](api_key, case, args.retries, args.timeout)
            guarded = frozen_guard(result["final_packet"], result["choice"])
            rawf.write(json.dumps(
                {"case": case, "arch": arch, "guarded_choice": guarded, **result},
                ensure_ascii=False,
            ) + "\n")
            rawf.flush()
            row = {
                "id": case["id"],
                "category": case["category"],
                "expected": case["expected"],
                "arch": arch,
                "choice": result["choice"],
                "guarded_choice": guarded,
                "correct": int(result["choice"] == case["expected"]),
                "guarded_correct": int(guarded == case["expected"]),
                "expected_p": result["expected_p"],
                "brier": result["brier"],
                "calls": result["calls"],
                "critical_path_ms": round(result["critical_path_ms"], 1),
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
            }
            rows.append(row)
            print(
                f"[{i:03d}/{len(items)}] {case['id']} {arch:24s} exp={case['expected']:15s} "
                f"got={str(result['choice']):15s} guard={guarded:15s} "
                f"P={result['expected_p']:.2f} ms={result['critical_path_ms']:.0f} in={result['input_tokens']}"
            )

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    per_arch = {}
    for arch in arches:
        rs = [r for r in rows if r["arch"] == arch]
        per_arch[arch] = {
            "n": len(rs),
            "accuracy": statistics.mean(r["correct"] for r in rs),
            "guarded_accuracy": statistics.mean(r["guarded_correct"] for r in rs),
            "mean_expected_p": statistics.mean(r["expected_p"] for r in rs),
            "mean_brier": statistics.mean(r["brier"] for r in rs),
            "mean_calls": statistics.mean(r["calls"] for r in rs),
            "mean_critical_path_ms": statistics.mean(r["critical_path_ms"] for r in rs),
            "mean_input_tokens": statistics.mean(r["input_tokens"] for r in rs),
        }

    meta = {
        "run_id": args.run_id,
        "holdout_sha256": FROZEN_HOLDOUT_SHA256,
        "model": MODEL,
        "api_url": API_URL,
        "architectures": per_arch,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("\n=== HYBRID HOLDOUT SUMMARY ===")
    for arch, s in per_arch.items():
        print(
            f"{arch:24s} acc={s['accuracy']:.3f} guard={s['guarded_accuracy']:.3f} "
            f"Pexp={s['mean_expected_p']:.3f} brier={s['mean_brier']:.4f} "
            f"calls={s['mean_calls']:.1f} ms={s['mean_critical_path_ms']:.0f} input={s['mean_input_tokens']:.0f}"
        )


if __name__ == "__main__":
    main()
