import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from sar_runtime import (
    AmbiguousProviderOutcome,
    CapabilityManifest,
    CapabilityManifestEntry,
    DurableRuntime,
    HTTPProviderAdapter,
    InMemoryDurableStore,
    InMemoryLeaseCoordinator,
    ProviderCapabilities,
    SQLiteProviderAdapter,
    ToolCallProposal,
    build_proposal,
    build_vote,
    issue_dar,
)


SERVER = Path(__file__).with_name("http_provider_reference_server.py")


@contextmanager
def provider_server(tmp_path, **caps):
    db = tmp_path / "provider.db"
    cmd = [
        sys.executable,
        str(SERVER),
        "--db", str(db),
        "--port", "0",
        "--idempotency", "1" if caps.get("idempotency", True) else "0",
        "--status-query", "1" if caps.get("status_query", True) else "0",
        "--fencing", "1" if caps.get("fencing", True) else "0",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = proc.stdout.readline()
        assert line, proc.stderr.read()
        info = json.loads(line)
        base_url = f"http://{info['host']}:{info['port']}"
        yield base_url, db, proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


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


def make_dar(m):
    p = build_proposal(
        "P1",
        [ToolCallProposal("local.write_file", {"path": "notes.md"})],
    )
    d = issue_dar(
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
    assert d is not None
    return d


def test_http_provider_dispatch_query_and_idempotency(tmp_path):
    with provider_server(tmp_path) as (base_url, db, _):
        adapter = HTTPProviderAdapter(base_url)
        kwargs = dict(
            action_id="A1",
            auth_id="AUTH1",
            proposal_hash="PH1",
            idempotency_key="ID1",
            fence=1,
            result={"value": "x"},
        )
        r1 = adapter.dispatch(**kwargs)
        r2 = adapter.dispatch(**kwargs)
        assert r1 == r2
        assert adapter.query("ID1") == r1
        assert SQLiteProviderAdapter(db).effect_count() == 1


def test_http_provider_rejects_stale_fence(tmp_path):
    with provider_server(tmp_path) as (base_url, db, _):
        adapter = HTTPProviderAdapter(base_url)
        adapter.dispatch(
            action_id="A2",
            auth_id="AUTH2",
            proposal_hash="PH2",
            idempotency_key="ID2",
            fence=2,
            result={"value": "new"},
        )
        stale = adapter.dispatch(
            action_id="A1",
            auth_id="AUTH1",
            proposal_hash="PH1",
            idempotency_key="ID1",
            fence=1,
            result={"value": "old"},
        )
        assert stale["status"] == "REJECTED_STALE_FENCE"
        assert SQLiteProviderAdapter(db).effect_count() == 1


def test_http_drop_after_commit_is_ambiguous_but_queryable(tmp_path):
    with provider_server(tmp_path) as (base_url, db, _):
        adapter = HTTPProviderAdapter(
            base_url,
            headers={"X-Test-Drop-First-Response": "1"},
        )
        with pytest.raises(AmbiguousProviderOutcome):
            adapter.dispatch(
                action_id="A1",
                auth_id="AUTH1",
                proposal_hash="PH1",
                idempotency_key="ID1",
                fence=1,
                result={"value": "x"},
            )

        receipt = adapter.query("ID1")
        assert receipt is not None
        assert receipt.status == "SUCCEEDED"
        assert SQLiteProviderAdapter(db).effect_count() == 1


def test_durable_runtime_recovers_ambiguous_http_response_via_query(tmp_path):
    with provider_server(tmp_path) as (base_url, db, _):
        m = manifest()
        store = InMemoryDurableStore()
        leases = InMemoryLeaseCoordinator()
        rt = DurableRuntime(m)
        rt.persist_dar(store=store, stream_id="ACT-1", dar=make_dar(m))

        adapter = HTTPProviderAdapter(
            base_url,
            headers={"X-Test-Drop-First-Response": "1"},
        )

        coc = rt.recover_action(
            store=store,
            stream_id="ACT-1",
            provider=adapter,
            leases=leases,
            resource_id="workspace",
            owner_id="R1",
        )
        assert coc is not None
        assert coc.status == "SUCCEEDED"
        assert SQLiteProviderAdapter(db).effect_count() == 1
