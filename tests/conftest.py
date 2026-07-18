"""Hermetic test-suite helpers: environment scrubbing for subprocess calls.

The WarrantOS test suite is hermetic: it never invokes external LLM
binaries (``claude``, ``codex``), never uses API keys, and never opens
network sockets. CI enforces this with a booby-trap ``claude`` shim on
PATH that exits 97 and records every invocation (see the ``hermetic``
job in .github/workflows/ci.yml).

Every test that launches a subprocess passes ``env=get_clean_env()`` so
that ambient credentials or grader overrides on a developer machine can
never route a test through an external tool. ``tests/test_hermetic.py``
audits this rule with an AST scan over the suite.

This module is stdlib-only and importable under both runners:

- ``python -m unittest discover -s tests`` puts ``tests/`` on
  ``sys.path``, so ``from conftest import get_clean_env`` resolves.
- pytest auto-loads ``conftest.py`` and the same import works.

LLM grading remains an explicit opt-in for humans running the eval
harness by hand (see docs/NO-API-KEY.md); the automated suite never
opts in.
"""

from __future__ import annotations

import os

# Environment variables that could route a subprocess to an external
# LLM tool, an API, or a non-default grader. Exact names.
_SCRUB_EXACT = (
    "CLAUDE_HOME",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "WARRANTOS_SIGNING_KEY",
)

# Prefixes: any variable starting with one of these is scrubbed.
# PROVENANCE_* covers grader selection/overrides (PROVENANCE_GRADER,
# PROVENANCE_LOCAL_GRADER_URL, PROVENANCE_DB, PROVENANCE_MODE, ...).
_SCRUB_PREFIXES = (
    "PROVENANCE_",
    "CLAUDE_CODE_",
)


def get_clean_env() -> dict:
    """Return a copy of ``os.environ`` safe for hermetic subprocesses.

    Removes external-tool homes, API credentials, and every
    ``PROVENANCE_*`` override so the child process always runs the
    default offline configuration. PATH and HOME are preserved (the CI
    booby-trap shim relies on PATH staying intact).

    Tests that deliberately need a PROVENANCE_* variable (for example
    the hook tests that set PROVENANCE_DB) should start from this dict
    and add back exactly the keys they mean to set::

        env = get_clean_env()
        env["PROVENANCE_DB"] = str(db_path)
        subprocess.run([...], env=env)
    """
    env = dict(os.environ)
    for key in _SCRUB_EXACT:
        env.pop(key, None)
    for key in list(env):
        if key.startswith(_SCRUB_PREFIXES):
            env.pop(key, None)
    return env


def assert_env_clean(env: dict) -> None:
    """Raise AssertionError if *env* still carries a scrubbed variable.

    Helper for tests that build their environment by hand.
    """
    leaked = [k for k in env if k in _SCRUB_EXACT or k.startswith(_SCRUB_PREFIXES)]
    # Deliberate re-additions (e.g. PROVENANCE_DB) are the caller's
    # explicit choice; this helper is for verifying a supposedly-clean
    # dict, so any hit is a failure.
    if leaked:
        raise AssertionError(
            "environment is not clean; leaked variables: %s" % sorted(leaked)
        )


def scrubbed_names() -> tuple:
    """Expose the exact-name scrub list (for the audit tests)."""
    return _SCRUB_EXACT


def scrubbed_prefixes() -> tuple:
    """Expose the prefix scrub list (for the audit tests)."""
    return _SCRUB_PREFIXES
