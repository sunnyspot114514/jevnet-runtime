from __future__ import annotations

import sqlite3
from pathlib import Path

from .lease import LeaseToken


class SQLiteLeaseCoordinator:
    """SQLite-backed monotonic lease/fencing coordinator.

    Acquiring a resource always increments its fence, including after process
    restart. Releasing a stale token never rewinds or clears a newer lease.
    """

    def __init__(self, path: str | Path, *, timeout: float = 10.0) -> None:
        self.path = str(Path(path))
        self.timeout = float(timeout)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.timeout)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leases (
                    resource_id TEXT PRIMARY KEY,
                    owner_id TEXT,
                    fence INTEGER NOT NULL
                )
                """
            )

    def acquire(self, resource_id: str, owner_id: str) -> LeaseToken:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT owner_id, fence
                FROM leases
                WHERE resource_id = ?
                """,
                (resource_id,),
            ).fetchone()

            if row is None:
                fence = 1
                conn.execute(
                    """
                    INSERT INTO leases(resource_id, owner_id, fence)
                    VALUES (?, ?, ?)
                    """,
                    (resource_id, owner_id, fence),
                )
            else:
                fence = int(row[1]) + 1
                conn.execute(
                    """
                    UPDATE leases
                    SET owner_id = ?, fence = ?
                    WHERE resource_id = ?
                    """,
                    (owner_id, fence, resource_id),
                )

            conn.commit()
            return LeaseToken(
                resource_id=resource_id,
                owner_id=owner_id,
                fence=fence,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def current(self, resource_id: str) -> LeaseToken | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT owner_id, fence
                FROM leases
                WHERE resource_id = ?
                """,
                (resource_id,),
            ).fetchone()

        if row is None or row[0] is None:
            return None

        return LeaseToken(
            resource_id=resource_id,
            owner_id=str(row[0]),
            fence=int(row[1]),
        )

    def integrity_check(self) -> str:
        with self._connect() as conn:
            return str(conn.execute("PRAGMA integrity_check").fetchone()[0])

    def release(self, token: LeaseToken) -> bool:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT owner_id, fence
                FROM leases
                WHERE resource_id = ?
                """,
                (token.resource_id,),
            ).fetchone()

            if (
                row is None
                or row[0] != token.owner_id
                or int(row[1]) != token.fence
            ):
                conn.rollback()
                return False

            conn.execute(
                """
                UPDATE leases
                SET owner_id = NULL
                WHERE resource_id = ?
                """,
                (token.resource_id,),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
