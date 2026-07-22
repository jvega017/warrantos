#!/usr/bin/env python3
"""Fail CI when public release truth drifts from release-manifest.json."""
from __future__ import annotations
import json
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check(publication: str = "local") -> list[str]:
    if publication not in {"local", "public"}:
        raise ValueError("publication must be local or public")
    manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8-sig"))
    version = manifest["version"]
    errors: list[str] = []
    package = re.search(r'^__version__\s*=\s*"([^"]+)"', (ROOT / "warrantos/__init__.py").read_text(encoding="utf-8-sig"), re.M)
    if not package or package.group(1) != version:
        errors.append("package version does not match manifest")
    distribution = manifest.get("distribution_surface_versions") or {}
    action_source = re.search(
        r"(?m)^warrantos==([^\s]+)$",
        (ROOT / "action-requirements.in").read_text(encoding="utf-8-sig"),
    )
    action_lock_text = (ROOT / "action-requirements.txt").read_text(encoding="utf-8-sig")
    action_lock = re.search(r"(?m)^warrantos==([^\s\\]+)", action_lock_text)
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8-sig"))
    marketplace = json.loads(
        (ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8-sig")
    )
    action_version = distribution.get("github_action_package")
    plugin_version = distribution.get("claude_plugin")
    if not action_source or not action_lock or {
        action_source.group(1), action_lock.group(1), action_version
    } != {action_version}:
        errors.append("GitHub Action source, lock, and release manifest versions disagree")
    if len(re.findall(r"(?m)^warrantos==", action_lock_text)) != 1:
        errors.append("GitHub Action lock must contain exactly one WarrantOS pin")
    if "--hash=sha256:" not in action_lock_text:
        errors.append("GitHub Action lock must hash-pin the WarrantOS distribution")
    marketplace_versions = {
        marketplace.get("metadata", {}).get("version"),
        *[row.get("version") for row in marketplace.get("plugins", [])],
    }
    if plugin.get("version") != plugin_version or marketplace_versions != {plugin_version}:
        errors.append("Claude plugin, marketplace, and release manifest versions disagree")
    onboarding = {
        "docs/QUICKSTART.md": {
            "required": ("cd warrantos", "warrantos demo --output", "passage_reproduced"),
            "forbidden": ("cd claude-provenance", "python -m cli.warrantos_cli",
                          "warrantos-pre-publish-gate.ps1", "08_Outputs/"),
        },
        "CONTRIBUTING.md": {
            "required": ("# Contributing to WarrantOS", "CPython 3.11 through 3.13",
                         "tools/check_release_truth.py"),
            "forbidden": ("# Contributing to claude-provenance", "cd claude-provenance",
                          "Python 3.8", "python cli/warrantos_cli.py"),
        },
    }
    for relative, contract in onboarding.items():
        text = (ROOT / relative).read_text(encoding="utf-8-sig")
        for token in contract["required"]:
            if token not in text:
                errors.append(f"{relative}: missing onboarding token {token!r}")
        for token in contract["forbidden"]:
            if token in text:
                errors.append(f"{relative}: obsolete onboarding token {token!r}")
    required = {
        "README.md": [version, "local release candidate", "citation_present", "support_verified", "warrantos-evidence"],
        "docs/STATUS.md": [version, "local release candidate", "Production qualified", "Production-qualified rows"],
        "docs/STACK.md": ["not production qualified", "citation_present", "support_verified"],
        "docs/LIMITATIONS.md": [version, "local release candidate", "citation_present", "support_verified"],
        "CHANGELOG.md": [version, "local-rc.1", "claim-support states", "pinned Ed25519 public key"],
        "SECURITY.md": [version, "local release candidate", f"no `v{version}` tag", "external pinned trust root"],
        "docs/PRODUCTION-DEPLOYMENT.md": ["not tagged or production qualified", "warrantos-trust-root/v1", "No production key", "support_verified"],
        "warrantos/cli/warrantos_cli.py": ["citation_present", "semantic support require explicit linked records"],
    }
    if set(manifest["truth_surfaces"]) != set(required):
        errors.append("manifest truth_surfaces does not match checker surface set")
    for relative, tokens in required.items():
        text = (ROOT / relative).read_text(encoding="utf-8-sig")
        for token in tokens:
            if token not in text:
                errors.append(f"{relative}: missing truth token {token!r}")
    status = (ROOT / "docs/STATUS.md").read_text(encoding="utf-8-sig")
    if "Production-qualified rows**: 0" not in status:
        errors.append("docs/STATUS.md must explicitly report zero production-qualified rows")
    if manifest.get("git_tag") is not None:
        errors.append("local release candidate must not claim a git tag")
    if manifest.get("production_qualified") is not False:
        errors.append("local release candidate must remain production_qualified false")
    production = manifest.get("production_verification") or {}
    if production.get("pinned_signer_required") is not True or production.get("bundled_production_key") is not False:
        errors.append("production verification must require a pinned signer and ship no production key")
    if publication == "public":
        expected_tag = f"v{version}"
        if manifest.get("release_status") != "public-beta":
            errors.append("public publication requires release_status public-beta")
        if manifest.get("git_tag") != expected_tag:
            errors.append(f"public publication requires git_tag {expected_tag}")
        if manifest.get("changelog_section") != version:
            errors.append("public publication requires a versioned changelog section")
        if action_version != version:
            errors.append("public publication requires the GitHub Action to install the release version")
        if plugin_version != version:
            errors.append("public publication requires Claude plugin surfaces to match the release version")
        public_text = "\n".join(
            (ROOT / name).read_text(encoding="utf-8-sig").casefold()
            for name in ("README.md", "SECURITY.md", "docs/STATUS.md", "docs/LIMITATIONS.md")
        )
        if "local release candidate" in public_text or f"no `v{version}` tag" in public_text:
            errors.append("public truth surfaces still contain local-acquisition blockers")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication", choices=["local", "public"], default="local")
    args = parser.parse_args()
    errors = check(args.publication)
    if errors:
        for error in errors:
            print("release-truth drift: " + error, file=sys.stderr)
        return 1
    print("release truth: consistent")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
