from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .codec import from_wire, to_wire


class DurableRecordCorruptionError(RuntimeError):
    """A persisted durable record failed its content checksum."""


def _payload_sha256(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


class SQLiteDurableStore:
    """SQLite-backed append-only DurableStore reference implementation.

    This backend is intended for local development and process-restart tests.
    SQLite is configured with WAL and synchronous=FULL. Each application-level
    record also carries a SHA-256 checksum so silent row mutation is detected
    during replay.

    These measures are useful reference semantics, not a validated guarantee
    against physical power loss, storage-controller faults, torn files, or disk
    corruption.
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
                    payload_sha256 TEXT NOT NULL,
                    PRIMARY KEY (stream_id, offset)
                )
                """
            )

            # Migration for databases created by earlier reference versions.
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(durable_records)"
                ).fetchall()
            }
            if "payload_sha256" not in columns:
                conn.execute(
                    "ALTER TABLE durable_records ADD COLUMN payload_sha256 TEXT"
                )

            rows = conn.execute(
                """
                SELECT stream_id, offset, payload_json
                FROM durable_records
                WHERE payload_sha256 IS NULL OR payload_sha256 = ''
                """
            ).fetchall()
            for stream_id, offset, payload in rows:
                conn.execute(
                    """
                    UPDATE durable_records
                    SET payload_sha256 = ?
                    WHERE stream_id = ? AND offset = ?
                    """,
                    (_payload_sha256(payload), stream_id, int(offset)),
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
        checksum = _payload_sha256(payload)
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
                    (
                        stream_id,
                        offset,
                        record_type,
                        payload_json,
                        payload_sha256
                    )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    stream_id,
                    offset,
                    record_type,
                    payload,
                    checksum,
                ),
            )
            conn.commit()
            return offset
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _decode_checked(
        self,
        *,
        stream_id: str,
        offset: int,
        payload: str,
        checksum: str | None,
    ) -> Any:
        actual = _payload_sha256(payload)
        if not checksum or actual != checksum:
            raise DurableRecordCorruptionError(
                f"DURABLE_RECORD_CHECKSUM_MISMATCH:"
                f"{stream_id}:{offset}"
            )
        return from_wire(json.loads(payload))

    def read(self, stream_id: str) -> tuple[Any, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT offset, payload_json, payload_sha256
                FROM durable_records
                WHERE stream_id = ?
                ORDER BY offset ASC
                """,
                (stream_id,),
            ).fetchall()

        return tuple(
            self._decode_checked(
                stream_id=stream_id,
                offset=int(offset),
                payload=payload,
                checksum=checksum,
            )
            for offset, payload, checksum in rows
        )

    def find_first(self, stream_id: str, record_type: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT offset, payload_json, payload_sha256
                FROM durable_records
                WHERE stream_id = ? AND record_type = ?
                ORDER BY offset ASC
                LIMIT 1
                """,
                (stream_id, record_type),
            ).fetchone()

        if row is None:
            return None

        offset, payload, checksum = row
        return self._decode_checked(
            stream_id=stream_id,
            offset=int(offset),
            payload=payload,
            checksum=checksum,
        )

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

    def integrity_check(self) -> str:
        with self._connect() as conn:
            return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
