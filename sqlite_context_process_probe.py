#!/usr/bin/env python3
"""Cross-process SQLite context recovery probe.

Default mode launches two independent Python child processes:
1. writer: creates durable conversation/memory/runtime state in SQLite;
2. reader: opens only the SQLite file and rebuilds the model context view.

The two views must hash identically.

This probes process-restart persistence and deterministic projection. It is not
a physical power-loss/filesystem durability test.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    ContextProjector,
    DurableRuntime,
    EventSourcedStore,
    InMemoryLeaseCoordinator,
    InMemoryProvider,
    SQLiteDurableStore,
    SessionLog,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)
from sar_runtime.util import stable_hash

OUT = Path("sqlite_context_process_probe_analysis.json")


def manifest():
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


def project(db: Path):
    backing = SQLiteDurableStore(db)
    view = ContextProjector(
        session=SessionLog(backing, "session:S1"),
        runtime_store=EventSourcedStore(backing),
    ).project(["ACT-1"]).as_prompt_state()
    return view


def write_world(db: Path):
    backing = SQLiteDurableStore(db)
    session = SessionLog(backing, "session:S1")
    session.append(
        "conversation/message",
        {"role": "user", "content": "write hello to notes.md"},
    )
    session.append(
        "memory/committed",
        {"key": "workspace", "value": "local"},
    )
    # This must never become model-visible after restart.
    session.append(
        "memory/proposed",
        {"key": "action_status", "value": "guessed-success"},
    )

    m = manifest()
    p = build_proposal(
        "P1",
        [ToolCallProposal(
            "local.write_file",
            {"path": "notes.md", "content": "hello"},
        )],
    )
    dar = issue_dar(
        proposal=p,
        votes=[
            build_vote("A1", p, True),
            build_vote("A2", p, True),
        ],
        threshold=2,
        manifest=m,
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert dar is not None

    store = EventSourcedStore(backing)
    rt = DurableRuntime(m)
    rt.persist_dar(store=store, stream_id="ACT-1", dar=dar)
    coc = rt.recover_action(
        store=store,
        stream_id="ACT-1",
        provider=InMemoryProvider(),
        leases=InMemoryLeaseCoordinator(),
        resource_id="workspace",
        owner_id="writer-process",
    )
    assert coc is not None

    view = project(db)
    return {
        "hash": stable_hash(view),
        "view": view,
    }


def read_world(db: Path):
    view = project(db)
    return {
        "hash": stable_hash(view),
        "view": view,
    }


def child(mode: str, db: Path):
    payload = write_world(db) if mode == "write" else read_world(db)
    print(json.dumps(payload, sort_keys=True))
    return 0


def orchestrate():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "runtime.db"
        script = Path(__file__).resolve()

        writer = subprocess.run(
            [sys.executable, str(script), "--mode", "write", "--db", str(db)],
            check=True,
            capture_output=True,
            text=True,
        )
        reader = subprocess.run(
            [sys.executable, str(script), "--mode", "read", "--db", str(db)],
            check=True,
            capture_output=True,
            text=True,
        )

        w = json.loads(writer.stdout.strip())
        r = json.loads(reader.stdout.strip())

        assert w["hash"] == r["hash"]
        assert w["view"] == r["view"]
        assert r["view"]["actions"][0]["status"] == "CANONICAL_SUCCEEDED"
        serialized = json.dumps(r["view"], sort_keys=True)
        assert "guessed-success" not in serialized

        result = {
            "cross_process_view_equal": True,
            "writer_hash": w["hash"],
            "reader_hash": r["hash"],
            "recovered_action_status": r["view"]["actions"][0]["status"],
            "uncommitted_memory_leaked": False,
            "backend": "SQLiteDurableStore",
            "sqlite_pragmas": ["journal_mode=WAL", "synchronous=FULL"],
            "limitation": (
                "Independent-process reopen test; not a physical power-loss "
                "or filesystem-corruption experiment."
            ),
        }
        OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        print("Cross-process SQLite context recovery PASS")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["write", "read"])
    p.add_argument("--db")
    return p.parse_args()


def main():
    args = parse_args()
    if args.mode:
        if not args.db:
            raise SystemExit("--db is required with --mode")
        return child(args.mode, Path(args.db))
    orchestrate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
