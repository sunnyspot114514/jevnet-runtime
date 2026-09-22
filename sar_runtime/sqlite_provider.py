from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .codec import from_wire, to_wire
from .types import ProviderCapabilities, ProviderReceipt


class SQLiteProviderAdapter:
    """File-backed reference ProviderAdapter.

    The provider database is intentionally separate from the runtime journal.
    This models the core recovery problem: the external effect may commit even
    when the runtime process dies before persisting the returned receipt.

    This is a local reference adapter, not a production external service.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        capabilities: ProviderCapabilities | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.path = str(Path(path))
        self._capabilities = capabilities or ProviderCapabilities(
            supports_idempotency=True,
            supports_status_query=True,
            supports_compensation=False,
            supports_fencing=True,
            supports_transactional_commit=False,
        )
        self.timeout = float(timeout)
        self._initialize()

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.timeout)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_meta (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO provider_meta(key, value)
                VALUES ('min_fence', 0)
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO provider_meta(key, value)
                VALUES ('call_count', 0)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_effects (
                    effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                )
                """
            )
            if self.capabilities.supports_idempotency:
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_provider_effects_idempotency
                    ON provider_effects(idempotency_key)
                    """
                )

    def _meta(self, conn: sqlite3.Connection, key: str) -> int:
        row = conn.execute(
            "SELECT value FROM provider_meta WHERE key = ?",
            (key,),
        ).fetchone()
        return int(row[0])

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: int) -> None:
        conn.execute(
            """
            INSERT INTO provider_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, int(value)),
        )

    def advance_fence(self, fence: int) -> None:
        if not self.capabilities.supports_fencing:
            return
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._meta(conn, "min_fence")
            self._set_meta(conn, "min_fence", max(current, int(fence)))
            conn.commit()

    def dispatch(
        self,
        *,
        action_id: str,
        auth_id: str,
        proposal_hash: str,
        idempotency_key: str,
        fence: int,
        result: dict[str, Any],
    ) -> ProviderReceipt | dict[str, Any]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            calls = self._meta(conn, "call_count") + 1
            self._set_meta(conn, "call_count", calls)

            min_fence = self._meta(conn, "min_fence")
            if (
                self.capabilities.supports_fencing
                and int(fence) < min_fence
            ):
                conn.commit()
                return {
                    "status": "REJECTED_STALE_FENCE",
                    "fence": int(fence),
                    "min_fence": min_fence,
                }

            if self.capabilities.supports_fencing:
                self._set_meta(
                    conn,
                    "min_fence",
                    max(min_fence, int(fence)),
                )

            if self.capabilities.supports_idempotency:
                row = conn.execute(
                    """
                    SELECT receipt_json
                    FROM provider_effects
                    WHERE idempotency_key = ?
                    LIMIT 1
                    """,
                    (idempotency_key,),
                ).fetchone()
                if row is not None:
                    conn.commit()
                    return from_wire(json.loads(row[0]))

            placeholder = ProviderReceipt(
                receipt_id="PENDING",
                action_id=action_id,
                auth_id=auth_id,
                proposal_hash=proposal_hash,
                idempotency_key=idempotency_key,
                fence=int(fence),
                status="SUCCEEDED",
                result=result,
            )
            payload = json.dumps(
                to_wire(placeholder),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            cursor = conn.execute(
                """
                INSERT INTO provider_effects(idempotency_key, receipt_json)
                VALUES (?, ?)
                """,
                (idempotency_key, payload),
            )
            effect_id = int(cursor.lastrowid)

            receipt = ProviderReceipt(
                receipt_id=f"SQLREC-{action_id}-{effect_id}",
                action_id=action_id,
                auth_id=auth_id,
                proposal_hash=proposal_hash,
                idempotency_key=idempotency_key,
                fence=int(fence),
                status="SUCCEEDED",
                result=result,
            )
            conn.execute(
                """
                UPDATE provider_effects
                SET receipt_json = ?
                WHERE effect_id = ?
                """,
                (
                    json.dumps(
                        to_wire(receipt),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    effect_id,
                ),
            )
            conn.commit()
            return receipt
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def query(self, idempotency_key: str) -> ProviderReceipt | None:
        if not self.capabilities.supports_status_query:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT receipt_json
                FROM provider_effects
                WHERE idempotency_key = ?
                ORDER BY effect_id ASC
                LIMIT 1
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return from_wire(json.loads(row[0]))

    def effect_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM provider_effects"
            ).fetchone()
        return int(row[0])

    def call_count(self) -> int:
        with self._connect() as conn:
            return self._meta(conn, "call_count")

    def integrity_check(self) -> str:
        with self._connect() as conn:
            return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
