from __future__ import annotations

import argparse

from .authorization import issue_dar
from .builders import build_proposal, build_vote
from .harness import build_default_harness
from .manifest import CapabilityManifest
from .types import CapabilityManifestEntry, ToolCallProposal


def demo_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        version=1,
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


def run_demo() -> int:
    manifest = demo_manifest()
    harness = build_default_harness(manifest)

    print("JevNet Runtime demo")
    print("===================")

    chmod = build_proposal(
        "P-chmod",
        [ToolCallProposal(
            "filesystem.chmod",
            {"path": "deploy.sh", "mode": "755"},
        )],
    )
    unanimous = [build_vote(a, chmod, True) for a in ("A1", "A2", "A3")]
    chmod_dar = issue_dar(
        proposal=chmod,
        votes=unanimous,
        threshold=2,
        manifest=manifest,
        action_id="ACT-chmod",
        auth_id="AUTH-chmod",
        idempotency_key="IDEM-chmod",
        auth_generation=1,
    )

    print()
    print("1) Correlated model approval does not override capability policy")
    print("   semantic votes: APPROVE / APPROVE / APPROVE")
    print("   tool: filesystem.chmod -> permission_change")
    print(f"   DAR issued: {chmod_dar is not None}")

    local = build_proposal(
        "P-local",
        [ToolCallProposal(
            "local.write_file",
            {"path": "notes.md", "content": "hello"},
        )],
    )
    local_votes = [build_vote(a, local, True) for a in ("A1", "A2")]
    dar = issue_dar(
        proposal=local,
        votes=local_votes,
        threshold=2,
        manifest=manifest,
        action_id="ACT-local",
        auth_id="AUTH-local",
        idempotency_key="IDEM-local",
        auth_generation=1,
    )
    assert dar is not None

    runtime = harness.service("durable_runtime")
    store = harness.service("store")
    provider = harness.service("provider")
    leases = harness.service("leases")

    runtime.persist_dar(store=store, stream_id=dar.action_id, dar=dar)
    coc1 = runtime.recover_action(
        store=store,
        stream_id=dar.action_id,
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="replica-1",
    )

    print()
    print("2) Allowed local capability executes through durable runtime")
    print(f"   external effects: {len(provider.effects)}")
    print(f"   COC status: {None if coc1 is None else coc1.status}")

    # Re-create the runtime service to simulate process restart.
    fresh = build_default_harness(
        manifest,
        backing_store=harness.service("backing_store"),
        provider=provider,
        leases=leases,
    )
    coc2 = fresh.service("durable_runtime").recover_action(
        store=fresh.service("store"),
        stream_id=dar.action_id,
        provider=provider,
        leases=leases,
        resource_id="workspace",
        owner_id="replica-2",
    )

    print()
    print("3) Restart/replay does not duplicate the effect")
    print(f"   same COC: {coc1 == coc2}")
    print(f"   external effects after restart: {len(provider.effects)}")

    approval = fresh.approval("demo-session", default_policy="ask", answerers=[])
    outcome = approval.request(
        action_id="ACT-external",
        summary="Send data to an external service",
    )

    print()
    print("4) Approval seam fails closed")
    print(f"   no answerer -> {outcome}")
    print(f"   grants authority: {approval.grants(outcome)}")

    print()
    print("Plugin/service topology:")
    for name, owner in fresh.topology()["services"].items():
        print(f"   {name:16s} <- {owner}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sar-runtime",
        description="State-Aware Runtime research prototype",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("demo", help="run the zero-key local runtime demo")
    sub.add_parser("topology", help="show the default plugin/service topology")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "demo"):
        return run_demo()

    if args.command == "topology":
        h = build_default_harness(demo_manifest())
        print(h.topology())
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
