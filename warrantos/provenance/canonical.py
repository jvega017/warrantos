"""Canonical JSON serialization for deterministic signatures.

This module provides the single source of truth for converting Python objects
to bytes for cryptographic operations. It ensures that all signature operations
(Python and JavaScript) work with identical canonical representations.

Features:
- Sorted keys for deterministic output
- No whitespace
- UTF-8 encoding
- Explicit rejection of NaN/Infinity (not valid JSON, cannot round-trip to JS)
"""

from __future__ import annotations

import json


def canonical_json_bytes(obj: dict) -> bytes:
    """Serialize a dict to canonical JSON bytes.

    Produces output identical to:
        json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)

    This is the single source of truth for all signature operations.

    Parameters
    ----------
    obj : dict
        The object to serialize.

    Returns
    -------
    bytes
        UTF-8 encoded canonical JSON (sorted keys, no whitespace).

    Raises
    ------
    ValueError
        If the object contains NaN or Infinity (not valid JSON).
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
