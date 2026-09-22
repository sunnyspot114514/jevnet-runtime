#!/usr/bin/env python3
"""Cross-process crash probe with remote HTTP provider and lease services.

Processes:
- HTTP provider server -> its own SQLite effect ledger
- HTTP lease server    -> its own SQLite lease/fence ledger
- runtime worker       -> SQLite runtime journal only
- recovery worker      -> fresh Python process

Cuts:
- after_intent
- after_http_effect
- after_receipt
- after_coc

The runtime talks to both provider and lease exclusively over HTTP.

This validates SAR contracts across real process/network boundaries on one host.
It is not a WAN, TLS, multi-host partition, or physical power-loss experiment.
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
from urllib import request

from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    ContextProjector,
    DurableRuntime,
    EventSourcedStore,
    HTTPLeaseCoordinator,
    HTTPProviderAdapter,
    ProviderReceipt,
    SQLiteDurableStore,
    SessionLog,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)
from sar_runtime.util import stable_hash

OUT = Path("http_runtime_crash_probe_analysis.json")
PROVIDER_SERVER = Path(__file__).with_name(
    "http_provider_reference_server.py"
)
LEASE_SERVER = Path(__file__).with_name(
    "http_lease_reference_server.py"
)

CUTS = (
    "after_intent",
    "after_http_effect",
    "after_receipt",
    "after_coc",
)


def hard_crash() -> None:
    if os.name == "posix":
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(86)


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


def runtime_store(db: Path):
    return EventSourcedStore(SQLiteDurableStore(db))


def prepare_runtime(db: Path) -> None:
    backing = SQLiteDurableStore(db)
    session = SessionLog(backing, "session:S1")
    session.append(
        "conversation/message",
        {"role": "user", "content": "write hello"},
    )
    session.append(
        "memory/committed",
        {"key": "scope", "value": "local"},
    )
    session.append(
        "memory/proposed",
        {"key": "status", "value": "guessed-success"},
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


class CrashAfterHTTPDispatch:
    def __init__(self, inner: HTTPProviderAdapter) -> None:
        self.inner = inner

    @property
    def capabilities(self):
        return self.inner.capabilities

    def advance_fence(self, fence: int) -> None:
        self.inner.advance_fence(fence)

    def query(self, idempotency_key: str):
        return self.inner.query(idempotency_key)

    def dispatch(self, **kwargs):
        receipt = self.inner.dispatch(**kwargs)
        if isinstance(receipt, ProviderReceipt):
            hard_crash()
        return receipt


def project(runtime_db: Path) -> dict[str, Any]:
    backing = SQLiteDurableStore(runtime_db)
    return ContextProjector(
        session=SessionLog(backing, "session:S1"),
        runtime_store=EventSourcedStore(backing),
    ).project(["ACT-1"]).as_prompt_state()


def get_json(url: str) -> dict[str, Any]:
    with request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def worker(
    *,
    runtime_db: Path,
    provider_url: str,
    lease_url: str,
    cut: str,
) -> int:
    inner_store = runtime_store(runtime_db)
    target = {
        "after_intent": "DispatchIntent",
        "after_receipt": "ProviderReceipt",
        "after_coc": "CanonicalOutcomeCommit",
    }.get(cut)
    store = (
        CrashAfterRecordStore(inner_store, target)
        if target is not None
        else inner_store
    )

    adapter = HTTPProviderAdapter(provider_url)
    provider = (
        CrashAfterHTTPDispatch(adapter)
        if cut == "after_http_effect"
        else adapter
    )

    result = DurableRuntime(manifest()).recover_action(
        store=store,
        stream_id="ACT-1",
        provider=provider,
        leases=HTTPLeaseCoordinator(lease_url),
        resource_id="workspace",
        owner_id="crashing-http-worker",
    )

    raise RuntimeError(
        f"defined cut did not crash: {cut}, result={result!r}"
    )


def recover(
    *,
    runtime_db: Path,
    provider_url: str,
    lease_url: str,
) -> dict[str, Any]:
    adapter = HTTPProviderAdapter(provider_url)
    leases = HTTPLeaseCoordinator(lease_url)

    result = DurableRuntime(manifest()).recover_action(
        store=runtime_store(runtime_db),
        stream_id="ACT-1",
        provider=adapter,
        leases=leases,
        resource_id="workspace",
        owner_id="http-recovery-worker",
    )

    view = project(runtime_db)
    records = runtime_store(runtime_db).read("ACT-1")
    current = leases.current("workspace")

    return {
        "result_type": (
            type(result).__name__
            if result is not None
            else None
        ),
        "result_status": getattr(result, "status", None),
        "context": view,
        "context_hash": stable_hash(view),
        "provider_metrics": get_json(
            f"{provider_url}/metrics"
        ),
        "lease_metrics": get_json(
            f"{lease_url}/metrics"
        ),
        "record_types": [
            type(x).__name__ for x in records
        ],
        "lease": (
            None
            if current is None
            else {
                "owner": current.owner_id,
                "fence": current.fence,
            }
        ),
    }


def start_service(
    script: Path,
    db: Path,
) -> tuple[subprocess.Popen, str]:
    proc = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--db", str(db),
            "--port", "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError(
            f"service failed to start: {proc.stderr.read()}"
        )
    info = json.loads(line)
    return proc, f"http://{info['host']}:{info['port']}"


def stop_service(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def run_child(args: list[str], *, expect_crash=False):
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *args],
        capture_output=True,
        text=True,
    )
    if expect_crash:
        if proc.returncode == 0:
            raise AssertionError(
                f"expected crash\n"
                f"stdout={proc.stdout}\n"
                f"stderr={proc.stderr}"
            )
        return proc

    if proc.returncode != 0:
        raise RuntimeError(
            f"child failed rc={proc.returncode}\n"
            f"stdout={proc.stdout}\n"
            f"stderr={proc.stderr}"
        )
    return json.loads(proc.stdout.strip())


def scenario(
    root: Path,
    cut: str | None,
) -> tuple[int | None, dict[str, Any], dict[str, Any]]:
    runtime_db = root / "runtime.db"
    prepare_runtime(runtime_db)

    provider_proc, provider_url = start_service(
        PROVIDER_SERVER,
        root / "provider.db",
    )
    lease_proc, lease_url = start_service(
        LEASE_SERVER,
        root / "lease.db",
    )

    try:
        if cut is not None:
            crash = run_child(
                [
                    "--mode", "worker",
                    "--cut", cut,
                    "--runtime-db", str(runtime_db),
                    "--provider-url", provider_url,
                    "--lease-url", lease_url,
                ],
                expect_crash=True,
            )
            crash_returncode = crash.returncode
        else:
            crash_returncode = None

        first = run_child(
            [
                "--mode", "recover",
                "--runtime-db", str(runtime_db),
                "--provider-url", provider_url,
                "--lease-url", lease_url,
            ]
        )
        second = run_child(
            [
                "--mode", "recover",
                "--runtime-db", str(runtime_db),
                "--provider-url", provider_url,
                "--lease-url", lease_url,
            ]
        )

        return crash_returncode, first, second
    finally:
        stop_service(lease_proc)
        stop_service(provider_proc)


def orchestrate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        ignore_cleanup_errors=True
    ) as td:
        root = Path(td)

        baseline_root = root / "baseline"
        baseline_root.mkdir()
        _, baseline, baseline_second = scenario(
            baseline_root,
            None,
        )

        assert baseline == baseline_second
        assert (
            baseline["result_type"]
            == "CanonicalOutcomeCommit"
        )
        assert (
            baseline["provider_metrics"]["effect_count"]
            == 1
        )
        assert (
            baseline["provider_metrics"]["integrity"]
            == "ok"
        )
        assert (
            baseline["lease_metrics"]["integrity"]
            == "ok"
        )

        rows = []
        for cut in CUTS:
            case_root = root / cut
            case_root.mkdir()

            rc, first, second = scenario(
                case_root,
                cut,
            )

            assert (
                first["result_type"]
                == "CanonicalOutcomeCommit"
            ), (cut, first)
            assert (
                first["provider_metrics"]["effect_count"]
                == 1
            ), (cut, first)
            assert (
                first["provider_metrics"]["integrity"]
                == "ok"
            )
            assert (
                first["lease_metrics"]["integrity"]
                == "ok"
            )
            assert (
                first["context_hash"]
                == baseline["context_hash"]
            )
            assert first["context"] == baseline["context"]
            assert (
                "guessed-success"
                not in json.dumps(first["context"])
            )
            assert first == second

            rows.append(
                {
                    "cut": cut,
                    "crash_returncode": rc,
                    "effect_count": first[
                        "provider_metrics"
                    ]["effect_count"],
                    "provider_call_count": first[
                        "provider_metrics"
                    ]["call_count"],
                    "context_matches_baseline": (
                        first["context_hash"]
                        == baseline["context_hash"]
                    ),
                    "fixed_point": first == second,
                    "lease": first["lease"],
                    "record_types": first["record_types"],
                    "provider_integrity": first[
                        "provider_metrics"
                    ]["integrity"],
                    "lease_integrity": first[
                        "lease_metrics"
                    ]["integrity"],
                }
            )

        result = {
            "evidence_type": (
                "cross_process_http_provider_and_lease_"
                "crash_probe"
            ),
            "cuts": list(CUTS),
            "baseline_context_hash": (
                baseline["context_hash"]
            ),
            "rows": rows,
            "all_effect_counts_one": all(
                r["effect_count"] == 1
                for r in rows
            ),
            "all_contexts_match": all(
                r["context_matches_baseline"]
                for r in rows
            ),
            "all_fixed_points": all(
                r["fixed_point"]
                for r in rows
            ),
            "all_remote_integrity_checks_ok": all(
                r["provider_integrity"] == "ok"
                and r["lease_integrity"] == "ok"
                for r in rows
            ),
            "limitations": [
                (
                    "Provider and lease run as separate "
                    "loopback HTTP processes on the same host."
                ),
                (
                    "This is not a WAN, multi-host, network-"
                    "partition, TLS, or physical power-loss "
                    "experiment."
                ),
            ],
        }

        OUT.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )
        return result


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--mode",
        choices=["worker", "recover"],
    )
    p.add_argument("--cut", choices=CUTS)
    p.add_argument("--runtime-db")
    p.add_argument("--provider-url")
    p.add_argument("--lease-url")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.mode == "worker":
        if not all(
            (
                args.cut,
                args.runtime_db,
                args.provider_url,
                args.lease_url,
            )
        ):
            raise SystemExit(
                "worker requires cut/runtime-db/"
                "provider-url/lease-url"
            )
        return worker(
            runtime_db=Path(args.runtime_db),
            provider_url=args.provider_url,
            lease_url=args.lease_url,
            cut=args.cut,
        )

    if args.mode == "recover":
        if not all(
            (
                args.runtime_db,
                args.provider_url,
                args.lease_url,
            )
        ):
            raise SystemExit(
                "recover requires runtime-db/"
                "provider-url/lease-url"
            )
        print(
            json.dumps(
                recover(
                    runtime_db=Path(args.runtime_db),
                    provider_url=args.provider_url,
                    lease_url=args.lease_url,
                ),
                sort_keys=True,
            )
        )
        return 0

    result = orchestrate()
    print(json.dumps(result, indent=2))
    print(
        "HTTP provider + lease crash probe PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
