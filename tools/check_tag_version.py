#!/usr/bin/env python3
"""Require a release tag to match the package's PEP 440 version exactly."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def package_version(root: Path = ROOT) -> str:
    text = (root / "warrantos" / "__init__.py").read_text(encoding="utf-8-sig")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("package version is missing")
    return match.group(1)


def check_tag(tag: str, root: Path = ROOT) -> list[str]:
    expected = "v" + package_version(root)
    return [] if tag == expected else [f"release tag {tag!r} must equal {expected!r}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    args = parser.parse_args(argv)
    errors = check_tag(args.tag)
    for error in errors:
        print("tag/version mismatch: " + error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
