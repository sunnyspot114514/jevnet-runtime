from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .types import CapabilityManifestEntry, ProposalRecord, ValidationResult
from .util import stable_hash


class CapabilityManifest:
    def __init__(
        self,
        *,
        version: int,
        entries: list[CapabilityManifestEntry] | tuple[CapabilityManifestEntry, ...],
        allowed_effects: set[str] | frozenset[str],
    ) -> None:
        self.version = int(version)
        self._entries = {e.tool_id: e for e in entries}
        self.allowed_effects = frozenset(allowed_effects)

    @property
    def hash(self) -> str:
        payload = {
            "version": self.version,
            "entries": {
                tool_id: asdict(entry)
                for tool_id, entry in sorted(self._entries.items())
            },
            "allowed_effects": sorted(self.allowed_effects),
        }
        return stable_hash(payload)

    def entry(self, tool_id: str) -> CapabilityManifestEntry | None:
        return self._entries.get(tool_id)

    def validate(self, proposal: ProposalRecord) -> ValidationResult:
        reasons: list[str] = []
        normalized: list[dict[str, Any]] = []

        if not proposal.calls:
            reasons.append("NO_CALLS")

        for call in proposal.calls:
            entry = self.entry(call.tool_id)
            if entry is None:
                reasons.append(f"UNKNOWN_TOOL:{call.tool_id}")
                normalized.append({
                    "tool_id": call.tool_id,
                    "args": call.args,
                    "effect_class": "UNKNOWN",
                    "scope": "UNKNOWN",
                    "reversible": False,
                })
                continue

            normalized.append({
                "tool_id": entry.tool_id,
                "args": call.args,
                "effect_class": entry.effect_class,
                "scope": entry.scope,
                "reversible": entry.reversible,
            })

            if entry.effect_class not in self.allowed_effects:
                reasons.append(
                    f"FORBIDDEN_EFFECT:{entry.tool_id}:{entry.effect_class}"
                )

            arg_scope = call.args.get("target_scope")
            if arg_scope in {"external", "cloud", "remote", "system"}:
                reasons.append(
                    f"ARG_SCOPE_CROSSES_BOUNDARY:{entry.tool_id}:{arg_scope}"
                )

        return ValidationResult(
            authorized=not reasons,
            reasons=tuple(reasons),
            normalized_calls=tuple(normalized),
            manifest_version=self.version,
            manifest_hash=self.hash,
        )

    def revalidate_dar(self, dar) -> tuple[bool, str]:
        if dar.manifest_version != self.version:
            return False, "STALE_MANIFEST_VERSION"
        if dar.manifest_hash != self.hash:
            return False, "MANIFEST_HASH_MISMATCH"

        for call in dar.normalized_calls:
            entry = self.entry(call["tool_id"])
            if entry is None:
                return False, f"TOOL_REMOVED:{call['tool_id']}"
            if entry.effect_class != call["effect_class"]:
                return False, f"CAPABILITY_CHANGED:{call['tool_id']}"
            if entry.effect_class not in self.allowed_effects:
                return False, f"NOW_FORBIDDEN:{call['tool_id']}"

        return True, "OK"
