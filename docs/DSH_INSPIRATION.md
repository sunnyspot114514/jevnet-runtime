# DSH Inspiration

JevNet Runtime is not a port or fork of DeepSeek Harness. It borrows several
architectural ideas that fit the State-Aware Runtime experiments.

Official project:

- https://github.com/deepseek-ai/deepseek-harness

## Design crosswalk

| DeepSeek Harness idea | JevNet Runtime analogue |
|---|---|
| Everything is a plugin / service seam | `PluginManager` + `ServiceRegistry` |
| Session append-only event log | `SessionLog` + `EventSourcedStore` |
| Fail-closed user approval | `ApprovalService` |
| Per-call sandbox / approval policy | Manifest validation and execution binding per capability call |
| Replaceable providers | `ProviderAdapter` / `DurableStore` / `LeaseCoordinator` |
| Replayable session policy | Durable approval-policy events |

## What we intentionally do not copy

DeepSeek Harness is a full agent harness with a much larger product boundary:
agent loop, tools, model adapters, MCP, UI, sandbox providers, profiles,
sessions, extensions, and more.

JevNet Runtime stays focused on one narrower question:

> How does a proposed model action earn durable authority to affect the world?

The package therefore keeps:
- proposal records;
- capability identity;
- approval/authorization;
- durable execution;
- provider observation;
- canonical outcomes;
- replicated commit evidence.

It does not attempt to reproduce DSH's UI, full plugin ecosystem, or sandbox.

## Why the event log matters

The important borrowed principle is not "use plugins everywhere." It is that
runtime truth should be reconstructable from durable events.

If a process crashes, the system should recover from:
- durable authorization;
- dispatch intent;
- provider reality;
- receipt/reconciliation;
- canonical outcome.

It should not need the old process to remember what it was doing.

## Why approval fails closed

A missing UI, disconnected approval channel, exception, or non-conforming
answer must never become implicit permission.

The reference `ApprovalService` therefore maps those cases to
`unavailable`.

This mirrors the general SAR principle:

> Lack of evidence for authority is not authority.
