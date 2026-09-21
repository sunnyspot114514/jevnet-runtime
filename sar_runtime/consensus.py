from __future__ import annotations

from .types import ReplicatedCommitCertificate


def build_commit_certificate(
    *,
    value_hash: str,
    ballot: int,
    acknowledgers: list[str] | tuple[str, ...],
    replica_set: list[str] | tuple[str, ...],
    quorum_size: int,
) -> ReplicatedCommitCertificate | None:
    replicas = tuple(sorted(set(replica_set)))
    quorum = tuple(sorted(set(acknowledgers)))

    if any(n not in replicas for n in quorum):
        return None
    if len(quorum) < quorum_size:
        return None

    return ReplicatedCommitCertificate(
        value_hash=value_hash,
        ballot=int(ballot),
        quorum=quorum,
        replica_set=replicas,
    )


def validate_commit_certificate(
    cert: ReplicatedCommitCertificate,
    *,
    expected_value_hash: str,
    quorum_size: int,
) -> bool:
    if cert.value_hash != expected_value_hash:
        return False
    if len(set(cert.quorum)) < quorum_size:
        return False
    if any(n not in cert.replica_set for n in cert.quorum):
        return False
    return True
