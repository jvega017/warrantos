#!/usr/bin/env python3
"""Fail CI when public release truth drifts from release-manifest.json."""
from __future__ import annotations
import json
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ARCHIVAL_ACQUISITION_SURFACES = {
    "docs/FULL-OVERVIEW.md": "ARCHIVED ACQUISITION WARNING",
    "docs/IMPROVEMENT-ROADMAP-2026-06-11.md": "ARCHIVED ACQUISITION WARNING",
}

BLOCKED_ACQUISITION_PATTERNS = {
    "package-index install": re.compile(
        r"(?i)(?:(?:python\s+-m\s+)?pip\s+install\s+(?!-e\b)|pipx\s+install\s+)"
        r"[\"']?(?:warrantos|claude-provenance)(?:[\"'\[\s]|$)"
    ),
    "zero-install package execution": re.compile(
        r"(?mi)^\s*uvx\s+(?:--from\s+\S+\s+)?warrantos\b"
    ),
    "advisory-affected GitHub Action": re.compile(
        r"jvega017/warrantos@v0\.10\.0", re.I
    ),
    "advisory-affected pre-commit ref": re.compile(
        r"(?mi)^\s*rev:\s*v0\.10\.0\s*$"
    ),
    "obsolete legacy module path": re.compile(
        r"python\s+-m\s+provenance\.mcp_server", re.I
    ),
}


def _published_markdown_inventory(root: Path) -> tuple[str, ...]:
    """Return the GitHub README plus every Markdown page published by MkDocs."""
    config_path = root / "mkdocs.yml"
    if not config_path.is_file():
        raise ValueError("mkdocs.yml is missing; published acquisition surfaces are unknown")
    config = config_path.read_text(encoding="utf-8-sig")
    matches = re.findall(r"(?m)^docs_dir:\s*([^\s#]+)\s*$", config)
    if len(matches) > 1:
        raise ValueError("mkdocs.yml declares docs_dir more than once")
    raw_docs_dir = matches[0].strip("\"'") if matches else "docs"
    docs_dir = Path(raw_docs_dir)
    if docs_dir.is_absolute() or ".." in docs_dir.parts:
        raise ValueError("mkdocs.yml docs_dir must stay inside the repository")
    published_root = root / docs_dir
    if not published_root.is_dir():
        raise ValueError(f"mkdocs.yml docs_dir does not exist: {raw_docs_dir}")
    published = tuple(
        path.relative_to(root).as_posix()
        for path in sorted(published_root.rglob("*.md"))
    )
    if not published:
        raise ValueError("mkdocs.yml docs_dir contains no Markdown pages")
    return ("README.md", *published)


def _check_acquisition_truth(root: Path, manifest: dict) -> list[str]:
    """Reject active acquisition CTAs while the latest public release is unsafe."""
    errors: list[str] = []
    distribution = manifest.get("distribution_surface_versions") or {}
    blocked = distribution.get("public_recommendation") == "blocked-p0-advisory"
    if not blocked:
        errors.append("public acquisition recommendation must remain blocked during the P0 advisory")
        return errors
    if distribution.get("recommended_current_path") != "authenticated-0.11.0b2-candidate-bundle":
        errors.append("current acquisition path must be the authenticated 0.11.0b2 candidate bundle")

    try:
        acquisition_surfaces = _published_markdown_inventory(root)
    except ValueError as exc:
        errors.append(f"published acquisition inventory unavailable: {exc}")
        return errors

    for relative in acquisition_surfaces:
        text = (root / relative).read_text(encoding="utf-8-sig")
        archival_marker = ARCHIVAL_ACQUISITION_SURFACES.get(relative)
        if archival_marker is not None:
            if archival_marker not in text:
                errors.append(
                    f"{relative}: archival acquisition allowance requires {archival_marker!r}"
                )
            continue
        for label, pattern in BLOCKED_ACQUISITION_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{relative}: blocked {label} CTA present during the P0 advisory")

    required_contracts = {
        "README.md": ("authenticated 0.11.0b2", "ExpectedManifestSha256"),
        "docs/index.md": ("authenticated 0.11.0b2", "ExpectedManifestSha256"),
        "docs/QUICKSTART.md": ("authenticated 0.11.0b2", "ExpectedManifestSha256"),
        "docs/DISTRIBUTION.md": ("authenticated\n0.11.0b2", "P0 artefact-binding"),
    }
    for relative, tokens in required_contracts.items():
        text = (root / relative).read_text(encoding="utf-8-sig")
        for token in tokens:
            if token not in text:
                errors.append(f"{relative}: missing acquisition-safety token {token!r}")
    return errors

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
    errors.extend(_check_acquisition_truth(ROOT, manifest))
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
            "required": ("install.ps1", "warrantos demo --output", "passage_reproduced"),
            "forbidden": ("cd claude-provenance", "python -m cli.warrantos_cli",
                          "warrantos-pre-publish-gate.ps1", "08_Outputs/"),
        },
        "docs/MCP-CONFIG.md": {
            "required": ("cd warrantos", "CPython 3.11 through 3.13",
                         "warrantos.provenance.mcp_server"),
            "forbidden": ("cd claude-provenance", "Python version below 3.8",
                          '"provenance.mcp_server"'),
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
        if distribution.get("public_recommendation") == "blocked-p0-advisory":
            errors.append("public publication requires the P0 acquisition block to be replaced by a promoted-version contract")
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
