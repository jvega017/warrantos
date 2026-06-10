"""provenance.clean_room: Layer 6 clean-room generation (discipline mode).

The writer produces the draft from the writer pack only. SPEC §7
identifies two conformance levels:

- **Level 1 — discipline mode (this module)**: the writer entry point
  accepts ONLY a writer pack and a writer-model identifier. Additional
  context kwargs are refused at the API surface. This does not
  prevent a process-isolation breach inside the writer call itself,
  but it makes the breach a deliberate engineering choice rather than
  an accidental thread.
- **Level 2 — subprocess isolation**: the writer call happens in a
  subprocess with a scrubbed environment. Deferred. SPEC-L6-R001.

The discipline-mode wrapper does NOT itself call any LLM. It returns
an InvocationPlan describing what the writer would be called with.
The actual call is the caller's responsibility (their model client,
their API key, their cost).

This separation keeps the WarrantOS pipeline LLM-agnostic and
testable without network or credentials.

Stdlib only. Python 3.8 compatible.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from warrantos.provenance.writer_pack import WriterPack


# Kwargs explicitly permitted on the writer invocation. Anything else
# raises at the API surface; this is the SPEC-L6-S001 discipline.
_PERMITTED_INVOCATION_KEYS = frozenset({
    "writer_pack",
    "writer_model",
    "writer_role",
    "max_tokens",
    "temperature",
})


@dataclass(frozen=True)
class InvocationPlan:
    """A plan describing how the writer SHOULD be invoked.

    The discipline mode produces this plan; the actual call is the
    caller's responsibility. The plan carries only the writer-pack
    contents plus the model identifier; no ledger rows, no process
    history, no tool traces.
    """

    writer_pack: Dict[str, Any]
    writer_model: str
    writer_role: str = "clean_room_writer"
    max_tokens: int = 4096
    temperature: float = 0.2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "warrantos-invocation-plan/v1",
            "writer_pack": dict(self.writer_pack),
            "writer_model": self.writer_model,
            "writer_role": self.writer_role,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }


def prepare_invocation(
    writer_pack: WriterPack,
    writer_model: str,
    **kwargs: Any,
) -> InvocationPlan:
    """Build a discipline-mode invocation plan.

    SPEC-L6-S001 discipline: only the kwargs in `_PERMITTED_INVOCATION_KEYS`
    are accepted. Any other keyword raises ValueError. This blocks the
    common accidental thread where context history or feedback gets
    passed through as a "system prompt" or "context" kwarg that the
    writer then narrates back into final prose.

    Parameters
    ----------
    writer_pack
        The Layer 5 writer pack.
    writer_model
        The writer's model identifier (used by the Layer 7 G3
        self-grounding check to decide whether the grader is a
        different actor).
    **kwargs
        Optional overrides limited to `writer_role`, `max_tokens`,
        and `temperature`. Any other key raises.

    Returns
    -------
    InvocationPlan

    Raises
    ------
    ValueError
        If any kwarg is outside the permitted set, or if writer_model
        is empty.
    """
    if not writer_model or not writer_model.strip():
        raise ValueError("writer_model SHALL be a non-empty string")

    if not isinstance(writer_pack, WriterPack):
        raise TypeError(
            "writer_pack must be a WriterPack instance (got %r)"
            % type(writer_pack).__name__
        )

    rejected: List[str] = [k for k in kwargs if k not in _PERMITTED_INVOCATION_KEYS]
    if rejected:
        raise ValueError(
            "SPEC-L6-S001 discipline: refusing extra context kwargs: %s. "
            "Permitted keys: %s"
            % (sorted(rejected), sorted(_PERMITTED_INVOCATION_KEYS))
        )

    pack_dict = writer_pack.to_dict()

    plan = InvocationPlan(
        writer_pack=pack_dict,
        writer_model=writer_model.strip(),
        writer_role=str(kwargs.get("writer_role", "clean_room_writer")),
        max_tokens=int(kwargs.get("max_tokens", 4096)),
        temperature=float(kwargs.get("temperature", 0.2)),
    )
    return plan


def list_permitted_kwargs() -> List[str]:
    """Return the sorted list of kwargs the discipline mode accepts.

    Useful for callers building UI or documentation around the
    invocation surface.
    """
    return sorted(_PERMITTED_INVOCATION_KEYS)


# ---------------------------------------------------------------------------
# Subprocess isolation (Level 2 conformance, SPEC-L6-R001)
# ---------------------------------------------------------------------------

# Environment variables permitted into the subprocess. Everything else
# is scrubbed. The allowlist below is the minimum needed for a Python
# subprocess to run on Windows/Linux/macOS. Caller-supplied additions
# go through the explicit `extra_env_allowlist` argument; this keeps
# accidental credential leakage out of the writer subprocess.
_DEFAULT_ENV_ALLOWLIST = frozenset({
    "PATH",
    "PYTHONIOENCODING",
    "SYSTEMROOT",   # Windows: stdlib calls fail without it
    "TEMP",         # Windows
    "TMP",          # Windows
    "LANG",         # POSIX locale
    "LC_ALL",
    "HOME",
    "USERPROFILE",  # Windows home
})


@dataclass(frozen=True)
class SubprocessRunResult:
    """Result of a clean-room subprocess invocation."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    scrubbed_env_keys: int = 0
    kept_env_keys: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "scrubbed_env_keys": self.scrubbed_env_keys,
            "kept_env_keys": self.kept_env_keys,
        }


def run_clean_room_subprocess(
    plan: InvocationPlan,
    command: Sequence[str],
    *,
    timeout: float = 60.0,
    extra_env_allowlist: Optional[Sequence[str]] = None,
    cwd: Optional[str] = None,
) -> SubprocessRunResult:
    """Run *command* as a subprocess with a scrubbed environment.

    SPEC-L6-R001 Level 2 conformance. The subprocess receives the
    InvocationPlan via stdin as a JSON object. The environment is
    scrubbed to the documented allowlist plus any caller-supplied
    extensions; any other variable from the parent process is
    suppressed. The subprocess sees:

    - stdin: ``plan.to_dict()`` serialised as JSON, no trailing
      newline.
    - env: only the allowlisted keys, with their parent values.
    - cwd: caller's choice (defaults to the parent's cwd).

    The subprocess SHOULD parse stdin as the writer pack + writer
    model + temperature/max_tokens. The caller is responsible for
    writing the model client; this function does not import any LLM
    SDK.

    Parameters
    ----------
    plan
        The InvocationPlan from `prepare_invocation()`.
    command
        Argv list for the subprocess (e.g. ``[sys.executable, "writer.py"]``).
    timeout
        Subprocess timeout in seconds. On timeout, returns a
        SubprocessRunResult with `timed_out=True` and exit_code=-1.
    extra_env_allowlist
        Additional environment variable names to pass through. Useful
        for an `ANTHROPIC_API_KEY` or similar credential the writer
        needs; passing through is explicit, not silent.
    cwd
        Working directory for the subprocess. Defaults to None (the
        parent's cwd).

    Returns
    -------
    SubprocessRunResult
    """
    if not isinstance(plan, InvocationPlan):
        raise TypeError(
            "plan must be an InvocationPlan (got %r)" % type(plan).__name__
        )
    if not command:
        raise ValueError("command SHALL be a non-empty argv sequence")

    parent_env = dict(os.environ)
    allowlist = set(_DEFAULT_ENV_ALLOWLIST)
    if extra_env_allowlist:
        for name in extra_env_allowlist:
            if name and isinstance(name, str):
                allowlist.add(name)

    kept_env: Dict[str, str] = {}
    for key in allowlist:
        if key in parent_env:
            kept_env[key] = parent_env[key]

    scrubbed = len(parent_env) - len(kept_env)
    kept = len(kept_env)

    plan_json = json.dumps(plan.to_dict())
    try:
        completed = subprocess.run(
            list(command),
            input=plan_json,
            capture_output=True,
            text=True,
            env=kept_env,
            cwd=cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return SubprocessRunResult(
            exit_code=-1,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            timed_out=True,
            scrubbed_env_keys=scrubbed,
            kept_env_keys=kept,
        )

    return SubprocessRunResult(
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        timed_out=False,
        scrubbed_env_keys=scrubbed,
        kept_env_keys=kept,
    )


def list_default_env_allowlist() -> List[str]:
    """Return the sorted list of env var names passed through to the
    clean-room subprocess by default. Callers needing to thread a
    credential through SHALL extend this via `extra_env_allowlist`.
    """
    return sorted(_DEFAULT_ENV_ALLOWLIST)
