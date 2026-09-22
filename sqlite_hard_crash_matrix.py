#!/usr/bin/env python3
"""Cross-process hard-crash matrix for durable runtime + model context.

Two independent SQLite databases model:
- runtime/session durable journal;
- external provider reality.

A child process is terminated at one of seven cut points:
DAR -> Intent -> Provider Effect -> Receipt -> Reconciliation -> COC -> Context

A fresh process then reopens both databases and recovers.

This validates process-crash/restart semantics of the reference SQLite
backends. It is not a physical power-loss or filesystem-corruption test.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    ContextProjector,
    DurableRuntime,
    EventSourcedStore,
    ProviderReceipt,
    SQLiteDurableStore,
    SQLiteLeaseCoordinator,
    SQLiteProviderAdapter,
    SessionLog,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)
from sar_runtime.util import stable_hash

OUT = Path("sqlite_hard_crash_matrix_analysis.json")

CUTS = (
    "after_dar",
    "after_intent",
    "after_provider_effect",
    "after_receipt",
    "after_reconciliation",
    "after_coc",
    "after_context_projection",
)


def manifest() -> CapabilityManifest:
    return CapabilityManifest(
        version=1,
        entries=[
            CapabilityManifestEntry(
                tool_id="local.write_file",
                effect_class="local_content_write",
                scope="local",
                reversible=True,
            )
        ],
        allowed_effects={"local_content_write"},
    )


def runtime_store(runtime_db: Path):
    return EventSourcedStore(SQLiteDurableStore(runtime_db))


def prepare_world(runtime_db: Path) -> None:
    backing = SQLiteDurableStore(runtime_db)
    session = SessionLog(backing, "session:S1")
    session.append(
        "conversation/message",
        {"role": "user", "content": "write hello to notes.md"},
    )
    session.append(
        "memory/committed",
        {"key": "workspace", "value": "local"},
    )
    session.append(
        "memory/proposed",
        {"key": "action_status", "value": "guessed-success"},
    )

    m = manifest()
    proposal = build_proposal(
        "P1",
        [
            ToolCallProposal(
                "local.write_file",
                {"path": "notes.md", "content": "hello"},
            )
        ],
    )
    dar = issue_dar(
        proposal=proposal,
        votes=[
            build_vote("A1", proposal, True),
            build_vote("A2", proposal, True),
        ],
        threshold=2,
        manifest=m,
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert dar is not None
    DurableRuntime(m).persist_dar(
        store=EventSourcedStore(backing),
        stream_id="ACT-1",
        dar=dar,
    )


def hard_crash() -> None:
    # POSIX SIGKILL avoids finally/atexit cleanup. Windows uses immediate exit.
    if os.name == "posix":
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(86)


class CrashAfterRecordStore:
    def __init__(self, inner, target_type: str) -> None:
        self.inner = inner
        self.target_type = target_type

    def append(self, stream_id: str, record: Any) -> int:
        offset = self.inner.append(stream_id, record)
        if type(record).__name__ == self.target_type:
            hard_crash()
        return offset

    def read(self, stream_id: str):
        return self.inner.read(stream_id)

    def find_first(self, stream_id: str, record_type: str):
        return self.inner.find_first(stream_id, record_type)


class CrashAfterDispatchProvider:
    def __init__(self, inner: SQLiteProviderAdapter) -> None:
        self.inner = inner

    @property
    def capabilities(self):
        return self.inner.capabilities

    def advance_fence(self, fence: int) -> None:
        self.inner.advance_fence(fence)

    def query(self, idempotency_key: str):
        return self.inner.query(idempotency_key)

    def dispatch(self, **kwargs):
        result = self.inner.dispatch(**kwargs)
        if isinstance(result, ProviderReceipt):
            hard_crash()
        return result


def project(runtime_db: Path) -> dict[str, Any]:
    backing = SQLiteDurableStore(runtime_db)
    return ContextProjector(
        session=SessionLog(backing, "session:S1"),
        runtime_store=EventSourcedStore(backing),
    ).project(["ACT-1"]).as_prompt_state()


def record_types(runtime_db: Path) -> list[str]:
    return [
        type(x).__name__
        for x in runtime_store(runtime_db).read("ACT-1")
    ]


def worker(
    runtime_db: Path,
    provider_db: Path,
    lease_db: Path,
    cut: str,
) -> int:
    if cut == "after_dar":
        hard_crash()

    inner_store = runtime_store(runtime_db)
    target = {
        "after_intent": "DispatchIntent",
        "after_receipt": "ProviderReceipt",
        "after_reconciliation": "ReconciliationRecord",
        "after_coc": "CanonicalOutcomeCommit",
    }.get(cut)
    store = (
        CrashAfterRecordStore(inner_store, target)
        if target is not None
        else inner_store
    )

    provider_inner = SQLiteProviderAdapter(provider_db)
    provider = (
        CrashAfterDispatchProvider(provider_inner)
        if cut == "after_provider_effect"
        else provider_inner
    )

    result = DurableRuntime(manifest()).recover_action(
        store=store,
        stream_id="ACT-1",
        provider=provider,
        leases=SQLiteLeaseCoordinator(lease_db),
        resource_id="workspace",
        owner_id="crashing-worker",
    )

    if cut == "after_context_projection":
        _ = project(runtime_db)
        hard_crash()

    # Every defined cut should terminate before normal return.
    raise RuntimeError(f"cut did not crash: {cut}, result={result!r}")


def recover(
    runtime_db: Path,
    provider_db: Path,
    lease_db: Path,
) -> dict[str, Any]:
    provider = SQLiteProviderAdapter(provider_db)
    leases = SQLiteLeaseCoordinator(lease_db)
    result = DurableRuntime(manifest()).recover_action(
        store=runtime_store(runtime_db),
        stream_id="ACT-1",
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="recovery-worker",
    )
    view = project(runtime_db)
    return {
        "result_type": type(result).__name__ if result is not None else None,
        "result_status": getattr(result, "status", None),
        "effect_count": provider.effect_count(),
        "provider_call_count": provider.call_count(),
        "context_hash": stable_hash(view),
        "context": view,
        "runtime_record_types": record_types(runtime_db),
        "integrity": {
            "runtime": SQLiteDurableStore(runtime_db).integrity_check(),
            "provider": provider.integrity_check(),
            "lease": leases.integrity_check(),
        },
        "current_lease": (
            None
            if leases.current("workspace") is None
            else {
                "owner_id": leases.current("workspace").owner_id,
                "fence": leases.current("workspace").fence,
            }
        ),
    }


def run_child(args: list[str], *, expect_crash: bool = False):
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *args],
        capture_output=True,
        text=True,
    )
    if expect_crash:
        if proc.returncode == 0:
            raise AssertionError(
                f"expected crash but child returned 0\nstdout={proc.stdout}\nstderr={proc.stderr}"
            )
        return proc
    if proc.returncode != 0:
        raise RuntimeError(
            f"child failed rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )
    return json.loads(proc.stdout.strip())


def setup_scenario(root: Path) -> tuple[Path, Path, Path]:
    runtime_db = root / "runtime.db"
    provider_db = root / "provider.db"
    lease_db = root / "lease.db"
    prepare_world(runtime_db)
    SQLiteProviderAdapter(provider_db)
    SQLiteLeaseCoordinator(lease_db)
    return runtime_db, provider_db, lease_db


def orchestrate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        base_root = Path(td) / "baseline"
        base_root.mkdir()
        runtime_db, provider_db, lease_db = setup_scenario(base_root)
        baseline = run_child(
            [
                "--mode", "recover",
                "--runtime-db", str(runtime_db),
                "--provider-db", str(provider_db),
                "--lease-db", str(lease_db),
            ]
        )
        assert baseline["effect_count"] == 1
        assert baseline["result_type"] == "CanonicalOutcomeCommit"

        rows = []
        for cut in CUTS:
            root = Path(td) / cut
            root.mkdir()
            rdb, pdb, ldb = setup_scenario(root)

            crash_proc = run_child(
                [
                    "--mode", "worker",
                    "--cut", cut,
                    "--runtime-db", str(rdb),
                    "--provider-db", str(pdb),
                    "--lease-db", str(ldb),
                ],
                expect_crash=True,
            )

            first = run_child(
                [
                    "--mode", "recover",
                    "--runtime-db", str(rdb),
                    "--provider-db", str(pdb),
                    "--lease-db", str(ldb),
                ]
            )
            second = run_child(
                [
                    "--mode", "recover",
                    "--runtime-db", str(rdb),
                    "--provider-db", str(pdb),
                    "--lease-db", str(ldb),
                ]
            )

            assert first["effect_count"] == 1, (cut, first)
            assert second["effect_count"] == 1, (cut, second)
            assert first["result_type"] == "CanonicalOutcomeCommit", (cut, first)
            assert second["result_type"] == "CanonicalOutcomeCommit", (cut, second)
            assert first["context_hash"] == baseline["context_hash"], cut
            assert second["context_hash"] == baseline["context_hash"], cut
            assert first["context"] == baseline["context"], cut
            assert "guessed-success" not in json.dumps(first["context"])
            assert first["integrity"] == {
                "runtime": "ok",
                "provider": "ok",
                "lease": "ok",
            }, (cut, first["integrity"])

            types = first["runtime_record_types"]
            assert types.count("DurableAuthorizationRecord") == 1, (cut, types)
            assert 1 <= types.count("DispatchIntent") <= 2, (cut, types)
            assert types.count("ProviderReceipt") == 1, (cut, types)
            assert types.count("ReconciliationRecord") == 1, (cut, types)
            assert types.count("CanonicalOutcomeCommit") == 1, (cut, types)

            rows.append(
                {
                    "cut": cut,
                    "crash_returncode": crash_proc.returncode,
                    "effect_count_after_recovery": first["effect_count"],
                    "provider_calls_after_recovery": first["provider_call_count"],
                    "context_matches_baseline": (
                        first["context_hash"] == baseline["context_hash"]
                    ),
                    "second_recovery_fixed_point": second == first,
                    "runtime_record_types": types,
                    "dispatch_intent_count": types.count("DispatchIntent"),
                    "current_lease": first["current_lease"],
                    "integrity": first["integrity"],
                }
            )

        result = {
            "evidence_type": "cross_process_hard_crash_matrix",
            "cuts": list(CUTS),
            "baseline_context_hash": baseline["context_hash"],
            "rows": rows,
            "all_effect_counts_one": all(
                r["effect_count_after_recovery"] == 1 for r in rows
            ),
            "all_contexts_match_baseline": all(
                r["context_matches_baseline"] for r in rows
            ),
            "all_second_recoveries_fixed_point": all(
                r["second_recovery_fixed_point"] for r in rows
            ),
            "all_sqlite_integrity_checks_ok": all(
                set(r["integrity"].values()) == {"ok"}
                for r in rows
            ),
            "limitations": [
                "Uses SQLite reference backends for runtime, provider, and lease/fence state.",
                "Processes are killed abruptly, but the experiment does not simulate physical power loss, torn writes, disk corruption, or filesystem reordering.",
            ],
        }
        OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["worker", "recover"])
    p.add_argument("--cut", choices=CUTS)
    p.add_argument("--runtime-db")
    p.add_argument("--provider-db")
    p.add_argument("--lease-db")
    return p.parse_args()


def main():
    args = parse_args()
    if args.mode == "worker":
        if (
            not args.cut
            or not args.runtime_db
            or not args.provider_db
            or not args.lease_db
        ):
            raise SystemExit(
                "worker requires --cut --runtime-db --provider-db --lease-db"
            )
        return worker(
            Path(args.runtime_db),
            Path(args.provider_db),
            Path(args.lease_db),
            args.cut,
        )
    if args.mode == "recover":
        if not args.runtime_db or not args.provider_db or not args.lease_db:
            raise SystemExit(
                "recover requires --runtime-db --provider-db --lease-db"
            )
        print(
            json.dumps(
                recover(
                    Path(args.runtime_db),
                    Path(args.provider_db),
                    Path(args.lease_db),
                ),
                sort_keys=True,
            )
        )
        return 0

    result = orchestrate()
    print(json.dumps(result, indent=2))
    print("SQLite hard-crash matrix PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
