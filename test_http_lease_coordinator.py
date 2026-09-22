import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from sar_runtime import (
    HTTPLeaseCoordinator,
    LeaseCoordinatorUnavailable,
    SQLiteLeaseCoordinator,
)


SERVER = Path(__file__).with_name("http_lease_reference_server.py")


@contextmanager
def lease_server(db):
    proc = subprocess.Popen(
        [
            sys.executable,
            str(SERVER),
            "--db", str(db),
            "--port", "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = proc.stdout.readline()
        assert line, proc.stderr.read()
        info = json.loads(line)
        yield f"http://{info['host']}:{info['port']}", proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def test_http_lease_acquire_current_release(tmp_path):
    db=tmp_path/"lease.db"
    with lease_server(db) as (base_url,_):
        leases=HTTPLeaseCoordinator(base_url)
        t1=leases.acquire("workspace","R1")
        assert t1.fence==1
        assert leases.current("workspace")==t1

        t2=leases.acquire("workspace","R2")
        assert t2.fence==2
        assert leases.current("workspace")==t2

        assert leases.release(t1) is False
        assert leases.release(t2) is True
        assert leases.current("workspace") is None


def test_http_lease_fence_survives_server_restart(tmp_path):
    db=tmp_path/"lease.db"

    with lease_server(db) as (base_url,_):
        t1=HTTPLeaseCoordinator(base_url).acquire("workspace","R1")
        assert t1.fence==1

    with lease_server(db) as (base_url,_):
        t2=HTTPLeaseCoordinator(base_url).acquire("workspace","R2")
        assert t2.fence==2

    assert SQLiteLeaseCoordinator(db).integrity_check()=="ok"


def test_http_lease_unavailable_fails_closed():
    leases=HTTPLeaseCoordinator(
        "http://127.0.0.1:1",
        timeout=0.1,
    )
    with pytest.raises(LeaseCoordinatorUnavailable):
        leases.acquire("workspace","R1")
