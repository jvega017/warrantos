"""Installed JSON schemas for WarrantOS claim/source exchange records."""
from __future__ import annotations

import json
from importlib.resources import files
from typing import Dict, Tuple

_SCHEMA_NAMES: Tuple[str, ...] = (
    "source-manifest-v1.json",
    "claim-binding-v1.json",
    "trust-root-v1.json",
)


def available_schemas() -> Tuple[str, ...]:
    """Return the stable resource names shipped in the distribution."""
    return _SCHEMA_NAMES


def load_schema(name: str) -> Dict[str, object]:
    """Load and parse a packaged schema without a repository path."""
    if name not in _SCHEMA_NAMES:
        raise ValueError("unknown WarrantOS schema: %s" % name)
    resource = files(__package__).joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


__all__ = ["available_schemas", "load_schema"]
