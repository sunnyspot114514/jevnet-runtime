from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .codec import from_wire, to_wire


class SQLiteDurableStore:
    """SQLite-backed append-only DurableStore reference implementation.

    This backend is intended for local development and process-restart tests.
    SQLite is configured with WAL and synchronous=FULL. That is materially more
    realistic than the in-memory store, but this project does not claim a
    validated power-loss / filesystem-fault guarantee from this reference
    implementation.
    """

    def __init__(self, path: str | Path, *, timeout: float = 10.0) -> None:
        self.path = str(Path(path))
        self.timeout = float(timeout)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.timeout)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_records (
                    stream_id TEXT NOT NULL,
                    offset INTEGER NOT NULL,
                    record_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (stream_id, offset)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_durable_records_type
                ON durable_records(stream_id, record_type, offset)
                """
            )

    def append(self, stream_id: str, record: Any) -> int:
        payload = json.dumps(
            to_wire(record),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        record_type = type(record).__name__

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT COALESCE(MAX(offset), -1) + 1
                FROM durable_records
                WHERE stream_id = ?
                """,
                (stream_id,),
            ).fetchone()
            offset = int(row[0])
            conn.execute(
                """
                INSERT INTO durable_records
                    (stream_id, offset, record_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (stream_id, offset, record_type, payload),
            )
            conn.commit()
            return offset
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def read(self, stream_id: str) -> tuple[Any, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM durable_records
                WHERE stream_id = ?
                ORDER BY offset ASC
                """,
                (stream_id,),
            ).fetchall()
        return tuple(
            from_wire(json.loads(payload))
            for (payload,) in rows
        )

    def find_first(self, stream_id: str, record_type: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM durable_records
                WHERE stream_id = ? AND record_type = ?
                ORDER BY offset ASC
                LIMIT 1
                """,
                (stream_id, record_type),
            ).fetchone()
        if row is None:
            return None
        return from_wire(json.loads(row[0]))

    def streams(self) -> tuple[str, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT stream_id
                FROM durable_records
                ORDER BY stream_id ASC
                """
            ).fetchall()
        return tuple(row[0] for row in rows)
