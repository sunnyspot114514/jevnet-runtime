#!/usr/bin/env python3
"""Capability Manifest authorization layer.

Core rule:
- Model/Agent may propose a tool_id + args.
- Model-supplied effect_class/risk metadata is untrusted.
- Runtime looks up the tool in an immutable/versioned capability registry.
- DAR binds to registry version/hash and normalized calls.
- Unknown tools fail closed.
- Bundles fail closed if ANY call crosses a forbidden effect boundary.
- Dispatcher revalidates the manifest hash/version before executing.

This directly addresses correlated semantic mistakes such as treating chmod as
"just a local reversible file operation": the registry classifies it as a
permission change regardless of model opinion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OUT = Path("capability_manifest_analysis.json")

ALLOWED_EFFECTS = {
    "local_content_write",
    "local_content_rename",
    "local_test_execution",
    "local_preview",
}

FORBIDDEN_EFFECTS = {
    "permission_change",
    "security_config_change",
    "credential_change",
    "external_message",
    "external_publish",
    "external_upload",
    "external_data_mutation",
    "financial_spend",
    "persistent_delete",
}

REGISTRY_V1 = {
    "local.write_file": {
        "effect_class": "local_content_write",
        "scope": "local",
        "reversible": True,
    },
    "local.rename_file": {
        "effect_class": "local_content_rename",
        "scope": "local",
        "reversible": True,
    },
    "local.run_mock_test": {
        "effect_class": "local_test_execution",
        "scope": "local",
        "reversible": True,
    },
    "local.preview_site": {
        "effect_class": "local_preview",
        "scope": "local",
        "reversible": True,
    },
    "filesystem.chmod": {
        "effect_class": "permission_change",
        "scope": "machine",
        "reversible": True,
    },
    "filesystem.setfacl": {
        "effect_class": "permission_change",
        "scope": "machine",
        "reversible": True,
    },
    "system.firewall_rule": {
        "effect_class": "security_config_change",
        "scope": "machine",
        "reversible": True,
    },
    "system.sshd_config": {
        "effect_class": "security_config_change",
        "scope": "machine",
        "reversible": True,
    },
    "credential.rotate": {
        "effect_class": "credential_change",
        "scope": "external",
        "reversible": False,
    },
    "email.send": {
        "effect_class": "external_message",
        "scope": "external",
        "reversible": False,
    },
    "blog.publish": {
        "effect_class": "external_publish",
        "scope": "external",
        "reversible": False,
    },
    "cloud.upload": {
        "effect_class": "external_upload",
        "scope": "external",
        "reversible": False,
    },
    "database.execute": {
        "effect_class": "external_data_mutation",
        "scope": "external",
        "reversible": False,
    },
    "finance.charge": {
        "effect_class": "financial_spend",
        "scope": "external",
        "reversible": False,
    },
    "cloud.delete": {
        "effect_class": "persistent_delete",
        "scope": "external",
        "reversible": False,
    },
    "git.commit": {
        "effect_class": "local_content_write",
        "scope": "local",
        "reversible": True,
    },
    "git.push": {
        "effect_class": "external_upload",
        "scope": "external",
        "reversible": False,
    },
}


def registry_hash(registry: dict[str, Any]) -> str:
    blob = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class Manifest:
    version: int
    registry: dict[str, Any]

    @property
    def hash(self) -> str:
        return registry_hash(self.registry)


MANIFEST_V1 = Manifest(version=1, registry=REGISTRY_V1)


def normalize_call(call: dict[str, Any], manifest: Manifest) -> dict[str, Any]:
    tool_id = call.get("tool_id")
    if tool_id not in manifest.registry:
        return {
            "tool_id": tool_id,
            "args": call.get("args", {}),
            "known": False,
            "effect_class": "UNKNOWN",
            "scope": "UNKNOWN",
            "reversible": False,
            "model_claimed_effect_class": call.get("effect_class"),
        }

    spec = manifest.registry[tool_id]
    return {
        "tool_id": tool_id,
        "args": call.get("args", {}),
        "known": True,
        "effect_class": spec["effect_class"],
        "scope": spec["scope"],
        "reversible": bool(spec["reversible"]),
        "model_claimed_effect_class": call.get("effect_class"),
    }


def validate_proposal(proposal: dict[str, Any], manifest: Manifest) -> dict[str, Any]:
    calls = proposal.get("calls", [])
    normalized = [normalize_call(c, manifest) for c in calls]

    reasons = []
    if not calls:
        reasons.append("NO_CALLS")

    for c in normalized:
        if not c["known"]:
            reasons.append(f"UNKNOWN_TOOL:{c['tool_id']}")
            continue
        if c["effect_class"] in FORBIDDEN_EFFECTS:
            reasons.append(f"FORBIDDEN_EFFECT:{c['tool_id']}:{c['effect_class']}")
        elif c["effect_class"] not in ALLOWED_EFFECTS:
            reasons.append(f"UNCLASSIFIED_EFFECT:{c['tool_id']}:{c['effect_class']}")

        # Local tools may carry path targets. Fail closed if explicitly external.
        target_scope = c["args"].get("target_scope")
        if target_scope in {"external", "cloud", "remote", "system"}:
            reasons.append(f"ARG_SCOPE_CROSSES_BOUNDARY:{c['tool_id']}:{target_scope}")

    authorized = len(reasons) == 0
    return {
        "authorized": authorized,
        "reasons": reasons,
        "normalized_calls": normalized,
        "manifest_version": manifest.version,
        "manifest_hash": manifest.hash,
    }


def issue_dar(proposal: dict[str, Any], manifest: Manifest) -> dict[str, Any] | None:
    validation = validate_proposal(proposal, manifest)
    if not validation["authorized"]:
        return None

    calls_hash = hashlib.sha256(
        json.dumps(
            validation["normalized_calls"],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    return {
        "kind": "DAR",
        "proposal_id": proposal["proposal_id"],
        "manifest_version": manifest.version,
        "manifest_hash": manifest.hash,
        "normalized_calls": validation["normalized_calls"],
        "calls_hash": calls_hash,
    }


def dispatch_validate(dar: dict[str, Any], current_manifest: Manifest) -> dict[str, Any]:
    if dar["manifest_version"] != current_manifest.version:
        return {"allowed": False, "reason": "STALE_MANIFEST_VERSION"}
    if dar["manifest_hash"] != current_manifest.hash:
        return {"allowed": False, "reason": "MANIFEST_HASH_MISMATCH"}

    # Recheck every call against current manifest instead of trusting DAR text.
    for c in dar["normalized_calls"]:
        tool_id = c["tool_id"]
        if tool_id not in current_manifest.registry:
            return {"allowed": False, "reason": f"TOOL_REMOVED:{tool_id}"}
        spec = current_manifest.registry[tool_id]
        if spec["effect_class"] != c["effect_class"]:
            return {"allowed": False, "reason": f"CAPABILITY_CHANGED:{tool_id}"}
        if spec["effect_class"] not in ALLOWED_EFFECTS:
            return {"allowed": False, "reason": f"NOW_FORBIDDEN:{tool_id}"}

    return {"allowed": True, "reason": "OK"}


SCENARIOS = {
    "local_write_allowed": {
        "proposal_id": "P1",
        "calls": [
            {
                "tool_id": "local.write_file",
                "args": {"path": "notes.md", "target_scope": "local"},
            }
        ],
    },
    "chmod_lies_about_effect": {
        "proposal_id": "P2",
        "calls": [
            {
                "tool_id": "filesystem.chmod",
                "args": {"path": "secrets.txt", "mode": "600", "target_scope": "local"},
                "effect_class": "local_content_write",
            }
        ],
    },
    "setfacl_lies_about_effect": {
        "proposal_id": "P3",
        "calls": [
            {
                "tool_id": "filesystem.setfacl",
                "args": {"path": "project.txt", "acl": "u:alice:rw"},
                "effect_class": "local_content_write",
            }
        ],
    },
    "mixed_bundle": {
        "proposal_id": "P4",
        "calls": [
            {
                "tool_id": "local.write_file",
                "args": {"path": "final.md", "target_scope": "local"},
            },
            {
                "tool_id": "cloud.upload",
                "args": {"path": "final.md", "bucket": "prod"},
            },
        ],
    },
    "unknown_tool": {
        "proposal_id": "P5",
        "calls": [
            {
                "tool_id": "mystery.super_safe_tool",
                "args": {},
                "effect_class": "local_content_write",
            }
        ],
    },
    "local_tool_external_scope": {
        "proposal_id": "P6",
        "calls": [
            {
                "tool_id": "local.write_file",
                "args": {"path": "s3://bucket/x", "target_scope": "external"},
            }
        ],
    },
    "git_commit_allowed": {
        "proposal_id": "P7",
        "calls": [{"tool_id": "git.commit", "args": {"message": "local"}}],
    },
    "git_push_rejected": {
        "proposal_id": "P8",
        "calls": [{"tool_id": "git.push", "args": {"remote": "origin"}}],
    },
}


def changed_manifest() -> Manifest:
    registry = json.loads(json.dumps(REGISTRY_V1))
    # Simulate policy/registry update that reclassifies local.write_file as forbidden.
    registry["local.write_file"]["effect_class"] = "persistent_delete"
    return Manifest(version=2, registry=registry)


def main():
    results = {}
    for name, proposal in SCENARIOS.items():
        validation = validate_proposal(proposal, MANIFEST_V1)
        dar = issue_dar(proposal, MANIFEST_V1)
        results[name] = {
            "validation": validation,
            "dar": dar,
        }
        print("\n", name)
        print(json.dumps(results[name], indent=2))

    assert results["local_write_allowed"]["validation"]["authorized"] is True
    assert results["git_commit_allowed"]["validation"]["authorized"] is True

    for name in (
        "chmod_lies_about_effect",
        "setfacl_lies_about_effect",
        "mixed_bundle",
        "unknown_tool",
        "local_tool_external_scope",
        "git_push_rejected",
    ):
        assert results[name]["validation"]["authorized"] is False
        assert results[name]["dar"] is None

    # The model's self-reported effect class cannot downgrade chmod/setfacl.
    chmod = results["chmod_lies_about_effect"]["validation"]["normalized_calls"][0]
    assert chmod["model_claimed_effect_class"] == "local_content_write"
    assert chmod["effect_class"] == "permission_change"

    # DAR is bound to manifest version/hash. Registry changes invalidate old DAR.
    dar = results["local_write_allowed"]["dar"]
    assert dar is not None
    current_ok = dispatch_validate(dar, MANIFEST_V1)
    changed = dispatch_validate(dar, changed_manifest())
    print("\nDISPATCH VALIDATION")
    print("same manifest", current_ok)
    print("changed manifest", changed)
    assert current_ok["allowed"] is True
    assert changed["allowed"] is False
    assert changed["reason"] == "STALE_MANIFEST_VERSION"

    OUT.write_text(json.dumps({
        "manifest_version": MANIFEST_V1.version,
        "manifest_hash": MANIFEST_V1.hash,
        "allowed_effects": sorted(ALLOWED_EFFECTS),
        "forbidden_effects": sorted(FORBIDDEN_EFFECTS),
        "scenarios": results,
        "dispatch_same_manifest": current_ok,
        "dispatch_changed_manifest": changed,
    }, indent=2), encoding="utf-8")

    print("\nCapability manifest invariants PASS")


if __name__ == "__main__":
    main()
