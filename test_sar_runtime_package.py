from dataclasses import replace

from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    InMemoryProvider,
    ProviderCapabilities,
    RuntimeEngine,
    ToolCallProposal,
    build_commit_certificate,
    issue_dar,
    validate_commit_certificate,
)
from sar_runtime.builders import build_proposal, build_vote


def manifest(version=1):
    return CapabilityManifest(
        version=version,
        entries=[
            CapabilityManifestEntry(
                tool_id="local.write_file",
                effect_class="local_content_write",
                scope="local",
                reversible=True,
            ),
            CapabilityManifestEntry(
                tool_id="filesystem.chmod",
                effect_class="permission_change",
                scope="machine",
                reversible=True,
            ),
        ],
        allowed_effects={"local_content_write"},
    )


def dar_for_local(m=None):
    m=m or manifest()
    p=build_proposal(
        "P-local",
        [ToolCallProposal("local.write_file",{"path":"notes.md","target_scope":"local"})],
    )
    votes=[
        build_vote("A1",p,True),
        build_vote("A2",p,True),
        build_vote("A3",p,False),
    ]
    dar=issue_dar(
        proposal=p,
        votes=votes,
        threshold=2,
        manifest=m,
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert dar is not None
    return p,dar


def test_manifest_veto_overrides_unanimous_semantic_approval():
    m=manifest()
    p=build_proposal(
        "P-chmod",
        [ToolCallProposal("filesystem.chmod",{"path":"secret","mode":"600"})],
    )
    votes=[build_vote(a,p,True) for a in ("A1","A2","A3")]
    dar=issue_dar(
        proposal=p,
        votes=votes,
        threshold=2,
        manifest=m,
        action_id="ACT-C",
        auth_id="AUTH-C",
        idempotency_key="IDEM-C",
        auth_generation=1,
    )
    assert dar is None


def test_duplicate_authorizer_identity_does_not_form_quorum():
    m=manifest()
    p=build_proposal("P-dup",[ToolCallProposal("local.write_file",{"path":"x"})])
    votes=[
        build_vote("A1",p,True),
        build_vote("A1",p,True),
        build_vote("A1",p,True),
    ]
    dar=issue_dar(
        proposal=p,
        votes=votes,
        threshold=2,
        manifest=m,
        action_id="ACT-D",
        auth_id="AUTH-D",
        idempotency_key="IDEM-D",
        auth_generation=1,
    )
    assert dar is None


def test_dar_dispatch_idempotency_fencing_reconciliation_and_certificate():
    m=manifest()
    _,dar=dar_for_local(m)
    engine=RuntimeEngine(m)
    provider=InMemoryProvider(
        capabilities=ProviderCapabilities(
            supports_idempotency=True,
            supports_status_query=True,
            supports_fencing=True,
        )
    )

    intent1=engine.build_dispatch_intent(dar=dar,fence=1)
    r1=engine.dispatch(dar=dar,intent=intent1,provider=provider)
    r2=engine.dispatch(dar=dar,intent=intent1,provider=provider)

    assert r1.receipt_id==r2.receipt_id
    assert len(provider.effects)==1

    # New owner advances the fence.
    provider.advance_fence(2)
    stale=engine.dispatch(dar=dar,intent=intent1,provider=provider)
    assert stale["status"]=="REJECTED_STALE_FENCE"

    forged=replace(r1,receipt_id="FORGED",auth_id="AUTH-FAKE")
    coc,recon=engine.reconcile(dar=dar,receipts=[forged,r1])
    assert coc is not None
    assert recon.accepted_receipt_id==r1.receipt_id
    assert ("FORGED","AUTH_MISMATCH") in recon.rejected

    cert=build_commit_certificate(
        value_hash=coc.coc_hash,
        ballot=7,
        acknowledgers=["R1","R2"],
        replica_set=["R1","R2","R3"],
        quorum_size=2,
    )
    assert cert is not None
    assert validate_commit_certificate(
        cert,
        expected_value_hash=coc.coc_hash,
        quorum_size=2,
    )


def test_manifest_version_change_invalidates_old_dar():
    m1=manifest(version=1)
    _,dar=dar_for_local(m1)
    engine1=RuntimeEngine(m1)
    engine1.build_dispatch_intent(dar=dar,fence=1)

    m2=manifest(version=2)
    engine2=RuntimeEngine(m2)
    try:
        engine2.build_dispatch_intent(dar=dar,fence=2)
    except ValueError as e:
        assert str(e)=="STALE_MANIFEST_VERSION"
    else:
        raise AssertionError("old DAR should be invalid under manifest v2")


def test_unknown_and_external_scope_fail_closed():
    m=manifest()

    unknown=build_proposal("P-u",[ToolCallProposal("unknown.tool",{})])
    assert not m.validate(unknown).authorized

    scoped=build_proposal(
        "P-s",
        [ToolCallProposal("local.write_file",{"path":"x","target_scope":"external"})],
    )
    assert not m.validate(scoped).authorized
