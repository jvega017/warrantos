"""provenance.pathguard: path containment helpers for WarrantOS.

B5 fix (T4). Provides:

- RUN_ID_RE: compile-time pattern restricting run IDs to safe characters.
- resolve_under: verify that a candidate path resolves inside a base directory,
  raising ValueError on traversal or escape attempts.

Design notes:

- Path.resolve() is used for both base and candidate so that symlinks,
  relative components, and OS-specific normalisation are all handled before
  the containment test.
- The containment test uses os.path.commonpath rather than a string
  startswith so that a base of /foo/bar does not mistakenly accept
  /foo/barbaz (a classic startswith false-positive).
- strict=False is passed to resolve() so that paths whose final component
  does not yet exist (a new run directory) are still resolved correctly
  without raising FileNotFoundError.

Python 3.11+. Stdlib only.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Union


# ---------------------------------------------------------------------------
# Run-ID validation
# ---------------------------------------------------------------------------

# Alphanumerics plus hyphen and underscore; 1 to 64 characters.
# This deliberately excludes path separators, dots, and other shell-special
# characters so a run_id value can never escape the runs directory.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------
# Path containment
# ---------------------------------------------------------------------------

def resolve_under(base: Path, candidate: Union[str, Path]) -> Path:
    """Resolve *candidate* and assert it falls at or within *base*.

    Parameters
    ----------
    base:
        The permitted root directory.  Need not exist.
    candidate:
        The path supplied by the caller.  Need not exist.

    Returns
    -------
    Path
        The resolved candidate path.

    Raises
    ------
    ValueError
        If the resolved candidate escapes *base*, with a message naming both
        the base and the resolved candidate.

    Notes
    -----
    Resolution uses ``Path.resolve(strict=False)`` so that paths whose tail
    component does not yet exist (e.g. a new run output directory) are
    accepted without error.  Containment is checked with
    ``os.path.commonpath`` rather than a string ``startswith`` to avoid the
    classic ``/foo/bar`` vs ``/foo/barbaz`` false-positive.
    """
    resolved_base = Path(base).resolve()
    resolved_candidate = Path(candidate).resolve()

    try:
        common = Path(os.path.commonpath([resolved_base, resolved_candidate]))
    except ValueError:
        # On Windows, commonpath raises ValueError for paths on different
        # drives, which is definitionally an escape.
        raise ValueError(
            "path escape: candidate %r is not under base %r"
            % (str(resolved_candidate), str(resolved_base))
        )

    if common != resolved_base:
        raise ValueError(
            "path escape: %r resolves to %r which is outside base %r"
            % (str(candidate), str(resolved_candidate), str(resolved_base))
        )

    return resolved_candidate
