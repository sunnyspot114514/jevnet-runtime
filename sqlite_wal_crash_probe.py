#!/usr/bin/env python3
"""SQLite WAL transaction crash probe.

A child process opens the same SQLite file used by SQLiteDurableStore, starts a
transaction, writes one or two records, and is killed either before or after
COMMIT.

Expected:
- killed before COMMIT -> none of that transaction becomes visible;
- killed after COMMIT -> the whole transaction is visible and checksum-valid.

This tests process-crash atomicity at the SQLite transaction boundary. It does
not simulate physical power loss, controller cache loss, torn pages, or disk
corruption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sar_runtime import SQLiteDurableStore

OUT = Path("sqlite_wal_crash_probe_analysis.json")

CASES = (
    ("one_before_commit", 1, False),
    ("one_after_commit", 1, True),
    ("two_before_commit", 2, False),
    ("two_after_commit", 2, True),
)


def hard_crash() -> None:
    if os.name == "posix":
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(86)


def payload(i: int) -> str:
    return json.dumps(
        {"record": i, "value": f"v{i}"},
        sort_keys=True,
        separators=(",", ":"),
    )


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def child(db: Path, count: int, commit_before_crash: bool) -> int:
    # Ensure the current schema exists.
    SQLiteDurableStore(db)

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("BEGIN IMMEDIATE")

    for i in range(count):
        p = payload(i)
        conn.execute(
            """
            INSERT INTO durable_records
                (
                    stream_id,
                    offset,
                    record_type,
                    payload_json,
                    payload_sha256
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            ("probe", i, "dict", p, checksum(p)),
        )

    if commit_before_crash:
        conn.commit()

    hard_crash()
    return 0


def integrity_check(db: Path) -> str:
    with sqlite3.connect(db) as conn:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])


def visible_rows(db: Path) -> tuple[Any, ...]:
    return SQLiteDurableStore(db).read("probe")


def run_case(
    root: Path,
    name: str,
    count: int,
    commit_before_crash: bool,
) -> dict[str, Any]:
    db = root / f"{name}.db"
    SQLiteDurableStore(db)

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--mode", "child",
            "--db", str(db),
            "--count", str(count),
            "--commit-before-crash", "1" if commit_before_crash else "0",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        raise AssertionError(f"child did not crash: {name}")

    rows = visible_rows(db)
    check = integrity_check(db)

    expected = count if commit_before_crash else 0
    assert len(rows) == expected, (name, rows)
    assert check == "ok", (name, check)

    return {
        "case": name,
        "records_attempted": count,
        "commit_returned_before_crash": commit_before_crash,
        "child_returncode": proc.returncode,
        "records_visible_after_reopen": len(rows),
        "sqlite_integrity_check": check,
    }


def orchestrate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        root = Path(td)
        rows = [
            run_case(root, name, count, committed)
            for name, count, committed in CASES
        ]

        result = {
            "evidence_type": "sqlite_transaction_process_crash_probe",
            "rows": rows,
            "all_precommit_writes_invisible": all(
                r["records_visible_after_reopen"] == 0
                for r in rows
                if not r["commit_returned_before_crash"]
            ),
            "all_postcommit_writes_visible": all(
                r["records_visible_after_reopen"] == r["records_attempted"]
                for r in rows
                if r["commit_returned_before_crash"]
            ),
            "all_integrity_checks_ok": all(
                r["sqlite_integrity_check"] == "ok"
                for r in rows
            ),
            "limitations": [
                "This is a process-crash test around SQLite COMMIT.",
                "It does not simulate physical power loss, torn pages, controller cache loss, disk corruption, or filesystem reordering.",
            ],
        }

        OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["child"])
    p.add_argument("--db")
    p.add_argument("--count", type=int)
    p.add_argument("--commit-before-crash")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "child":
        if args.db is None or args.count is None or args.commit_before_crash is None:
            raise SystemExit("child mode requires --db --count --commit-before-crash")
        return child(
            Path(args.db),
            args.count,
            args.commit_before_crash == "1",
        )

    result = orchestrate()
    print(json.dumps(result, indent=2))
    print("SQLite WAL crash probe PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
