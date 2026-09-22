from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .approval import ApprovalService
from .durable_runtime import DurableRuntime
from .events import EventSourcedStore, SessionLog
from .lease import InMemoryLeaseCoordinator
from .manifest import CapabilityManifest
from .plugins import PluginContext, PluginManager, ValuePlugin
from .provider import InMemoryProvider
from .store import InMemoryDurableStore


@dataclass
class RuntimePlugin:
    name: str = "runtime"
    requires: tuple[str, ...] = ("manifest",)

    def setup(self, ctx: PluginContext):
        manifest = ctx.require("manifest")
        ctx.provide("durable_runtime", DurableRuntime(manifest))
        return None


@dataclass
class EventStorePlugin:
    name: str = "event-store"
    requires: tuple[str, ...] = ("backing_store",)

    def setup(self, ctx: PluginContext):
        backing = ctx.require("backing_store")
        ctx.provide("store", EventSourcedStore(backing))
        return None


class Harness:
    """Composable runtime assembly inspired by DSH service seams.

    The harness owns composition, not business logic. Services remain
    independently replaceable.
    """

    def __init__(self) -> None:
        self.plugins = PluginManager()

    def install(self, plugin) -> "Harness":
        self.plugins.install(plugin)
        return self

    def start(self) -> "Harness":
        self.plugins.start()
        return self

    def stop(self) -> None:
        self.plugins.stop()

    def service(self, name: str) -> Any:
        return self.plugins.service(name)

    def session_log(self, session_id: str) -> SessionLog:
        backing = self.service("backing_store")
        return SessionLog(backing, f"session:{session_id}")

    def approval(
        self,
        session_id: str,
        *,
        default_policy: str = "ask",
        answerers=None,
    ) -> ApprovalService:
        return ApprovalService(
            session=self.session_log(session_id),
            default_policy=default_policy,
            answerers=answerers,
        )

    def topology(self) -> dict[str, Any]:
        return self.plugins.topology()


def build_default_harness(
    manifest: CapabilityManifest,
    *,
    backing_store=None,
    provider=None,
    leases=None,
) -> Harness:
    """Reference bundle with replaceable service seams."""

    backing_store = backing_store or InMemoryDurableStore()
    provider = provider or InMemoryProvider()
    leases = leases or InMemoryLeaseCoordinator()

    h = Harness()
    h.install(ValuePlugin("manifest", "manifest", manifest))
    h.install(ValuePlugin("backing-store", "backing_store", backing_store))
    h.install(EventStorePlugin())
    h.install(ValuePlugin("provider", "provider", provider))
    h.install(ValuePlugin("leases", "leases", leases))
    h.install(RuntimePlugin())
    h.start()
    return h
