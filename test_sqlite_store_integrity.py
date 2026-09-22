import sqlite3

import pytest

from sar_runtime import (
    DurableRecordCorruptionError,
    SQLiteDurableStore,
)


def test_sqlite_store_detects_payload_tampering(tmp_path):
    db=tmp_path/"runtime.db"
    store=SQLiteDurableStore(db)
    store.append("S1",{"value":"original"})

    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            UPDATE durable_records
            SET payload_json = ?
            WHERE stream_id = 'S1' AND offset = 0
            """,
            ('{"value":"tampered"}',),
        )
        conn.commit()

    reopened=SQLiteDurableStore(db)
    with pytest.raises(
        DurableRecordCorruptionError,
        match="DURABLE_RECORD_CHECKSUM_MISMATCH:S1:0",
    ):
        reopened.read("S1")


def test_sqlite_store_migrates_legacy_rows_with_checksum(tmp_path):
    db=tmp_path/"legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE durable_records (
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
            INSERT INTO durable_records
                (stream_id, offset, record_type, payload_json)
            VALUES ('S1', 0, 'dict', '{"value":"legacy"}')
            """
        )
        conn.commit()

    store=SQLiteDurableStore(db)
    assert store.read("S1")==({"value":"legacy"},)

    with sqlite3.connect(db) as conn:
        checksum=conn.execute(
            """
            SELECT payload_sha256
            FROM durable_records
            WHERE stream_id='S1' AND offset=0
            """
        ).fetchone()[0]
    assert isinstance(checksum,str)
    assert len(checksum)==64
