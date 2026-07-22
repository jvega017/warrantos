#!/usr/bin/env python3
"""Fail CI when public release truth drifts from release-manifest.json."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check() -> list[str]:
    manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8-sig"))
    version = manifest["version"]
    errors: list[str] = []
    package = re.search(r'^__version__\s*=\s*"([^"]+)"', (ROOT / "warrantos/__init__.py").read_text(encoding="utf-8-sig"), re.M)
    if not package or package.group(1) != version:
        errors.append("package version does not match manifest")
    required = {
        "README.md": [version, "local release candidate", "citation_present", "support_verified", "warrantos-evidence"],
        "docs/STATUS.md": [version, "local release candidate", "Production qualified", "Production-qualified rows"],
        "docs/STACK.md": ["not production qualified", "citation_present", "support_verified"],
        "docs/LIMITATIONS.md": [version, "local release candidate", "citation_present", "support_verified"],
        "CHANGELOG.md": [version, "local-rc.1", "claim-support states", "pinned Ed25519 public key"],
        "SECURITY.md": [version, "local release candidate", "no `v0.11.0` tag", "external pinned trust root"],
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
    return errors

def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print("release-truth drift: " + error, file=sys.stderr)
        return 1
    print("release truth: consistent")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
