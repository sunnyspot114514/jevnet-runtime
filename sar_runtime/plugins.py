from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable


class ServiceRegistry:
    """Small typed-by-name service registry.

    The registry owns service identity; providers own mechanics. Duplicate
    providers fail loudly instead of silently replacing each other.
    """

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}
        self._owners: dict[str, str] = {}

    def provide(self, name: str, service: Any, *, owner: str) -> None:
        if name in self._services:
            raise RuntimeError(
                f"SERVICE_ALREADY_PROVIDED:{name}:"
                f"{self._owners[name]}->{owner}"
            )
        self._services[name] = service
        self._owners[name] = owner

    def get(self, name: str) -> Any:
        if name not in self._services:
            raise KeyError(f"SERVICE_UNAVAILABLE:{name}")
        return self._services[name]

    def has(self, name: str) -> bool:
        return name in self._services

    def remove_owner(self, owner: str) -> None:
        names = [n for n, o in self._owners.items() if o == owner]
        for name in names:
            self._services.pop(name, None)
            self._owners.pop(name, None)

    def snapshot(self) -> dict[str, str]:
        return dict(sorted(self._owners.items()))


class PluginContext:
    def __init__(self, services: ServiceRegistry, plugin_name: str) -> None:
        self.services = services
        self.plugin_name = plugin_name

    def provide(self, name: str, service: Any) -> None:
        self.services.provide(name, service, owner=self.plugin_name)

    def require(self, name: str) -> Any:
        return self.services.get(name)


@runtime_checkable
class Plugin(Protocol):
    name: str
    requires: tuple[str, ...]

    def setup(self, ctx: PluginContext) -> Callable[[], None] | None:
        ...


@dataclass
class ValuePlugin:
    """Provide one pre-built service through the plugin lifecycle."""

    name: str
    service_name: str
    value: Any
    requires: tuple[str, ...] = ()

    def setup(self, ctx: PluginContext):
        ctx.provide(self.service_name, self.value)
        return None


class PluginManager:
    """Dependency-aware plugin lifecycle.

    Plugins activate only after every required service exists. Unresolved
    dependencies fail loudly at startup.
    """

    def __init__(self) -> None:
        self.services = ServiceRegistry()
        self._plugins: list[Plugin] = []
        self._active: list[tuple[Plugin, Callable[[], None] | None]] = []

    def install(self, plugin: Plugin) -> None:
        if any(p.name == plugin.name for p in self._plugins):
            raise RuntimeError(f"PLUGIN_ALREADY_INSTALLED:{plugin.name}")
        self._plugins.append(plugin)

    def start(self) -> None:
        pending = list(self._plugins)
        try:
            while pending:
                progressed = False
                for plugin in list(pending):
                    if all(self.services.has(dep) for dep in plugin.requires):
                        ctx = PluginContext(self.services, plugin.name)
                        try:
                            cleanup = plugin.setup(ctx)
                        except Exception:
                            self.services.remove_owner(plugin.name)
                            raise
                        self._active.append((plugin, cleanup))
                        pending.remove(plugin)
                        progressed = True
                if not progressed:
                    detail = {
                        p.name: [
                            dep for dep in p.requires
                            if not self.services.has(dep)
                        ]
                        for p in pending
                    }
                    raise RuntimeError(
                        f"UNRESOLVED_PLUGIN_DEPENDENCIES:{detail}"
                    )
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        for plugin, cleanup in reversed(self._active):
            if cleanup is not None:
                cleanup()
            self.services.remove_owner(plugin.name)
        self._active.clear()

    def service(self, name: str) -> Any:
        return self.services.get(name)

    def topology(self) -> dict[str, Any]:
        return {
            "plugins": [
                {
                    "name": p.name,
                    "requires": list(p.requires),
                    "active": any(ap.name == p.name for ap, _ in self._active),
                }
                for p in self._plugins
            ],
            "services": self.services.snapshot(),
        }
