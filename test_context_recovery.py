from sar_runtime import (
    CapabilityManifest,
    CapabilityManifestEntry,
    ContextProjector,
    EventSourcedStore,
    InMemoryDurableStore,
    SessionLog,
    ToolCallProposal,
    UnresolvedOutcome,
    build_proposal,
    build_vote,
    issue_dar,
)


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
    p=build_proposal(
        "P1",
        [ToolCallProposal("local.write_file",{"path":"notes.md"})],
    )
    d=issue_dar(
        proposal=p,
        votes=[build_vote("A1",p,True),build_vote("A2",p,True)],
        threshold=2,
        manifest=m,
        action_id="ACT-1",
        auth_id="AUTH-1",
        idempotency_key="IDEM-1",
        auth_generation=1,
    )
    assert d is not None
    return d


def test_unresolved_action_never_projects_as_success():
    backing=InMemoryDurableStore()
    store=EventSourcedStore(backing)
    session=SessionLog(backing,"session:S1")
    d=make_dar(manifest())
    store.append("ACT-1",d)
    store.append(
        "ACT-1",
        UnresolvedOutcome(
            action_id="ACT-1",
            auth_id="AUTH-1",
            idempotency_key="IDEM-1",
            reason="AMBIGUOUS_PROVIDER_OUTCOME_WITHOUT_RECONCILIATION_PRIMITIVE",
            retry_safe=False,
            required_operator_action="RECONCILE_EXTERNALLY_OR_ESCALATE; DO_NOT_BLINDLY_RETRY",
        ),
    )

    view=ContextProjector(
        session=session,
        runtime_store=store,
    ).project(["ACT-1"]).as_prompt_state()

    action=view["actions"][0]
    assert action["status"]=="UNRESOLVED"
    assert action["canonical_result"] is None
    assert "AMBIGUOUS_PROVIDER_OUTCOME" in action["unresolved_reason"]


def test_uncommitted_memory_event_is_not_model_visible():
    backing=InMemoryDurableStore()
    session=SessionLog(backing,"session:S1")
    session.append("memory/proposed",{"key":"x","value":"wrong"})
    session.append("memory/committed",{"key":"y","value":"right"})

    view=ContextProjector(
        session=session,
        runtime_store=EventSourcedStore(backing),
    ).project([]).as_prompt_state()

    assert view["memory_facts"]==[{"key":"y","value":"right"}]
    assert "wrong" not in str(view)
