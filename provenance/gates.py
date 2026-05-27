"""provenance.gates: Layer 7 quality gates above the boundary scan.

The boundary scan (Layer 7 G1) lives in `context_admissibility.py`.
This module hosts the additional gates:

- **G3 self-grounding** (SPEC-L7-S003, SPEC-L7-N003, SPEC-L7-N004,
  INV-006): same-model self-verification SHALL flag
  `requires_external_grounding`. Same-family verification SHALL be
  flagged in the CBOM as `cross_model = family_match`. The grader
  SHOULD belong to a different model family per a documented
  registry.

G4 (contamination scan) and G5 (calibration emission) are NOT BUILT
in v0.5. Stubs in this module raise NotImplementedError with a clear
pointer to the deferred reason; tests assert the stubs raise rather
than silently passing.

Stdlib only. Python 3.8 compatible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Model family registry (SPEC-L7-N004)
# ---------------------------------------------------------------------------

# Each entry maps a family-id pattern to a stable family name. The
# patterns are deliberately permissive: a model identifier matches a
# family when the family prefix appears as a token in the identifier.
_FAMILY_REGISTRY = (
    ("anthropic-claude", re.compile(r"\bclaude[-_]?[\w.]+", re.I)),
    ("openai-gpt", re.compile(r"\bgpt[-_]?[\w.]+", re.I)),
    ("google-gemini", re.compile(r"\bgemini[-_]?[\w.]+", re.I)),
    ("meta-llama", re.compile(r"\bllama[-_]?[\w.]+", re.I)),
    ("xai-grok", re.compile(r"\bgrok[-_]?[\w.]+", re.I)),
    ("mistral", re.compile(r"\bmistral[-_]?[\w.]+", re.I)),
    ("cohere", re.compile(r"\bcommand[-_]?[\w.]*|cohere[-_]?[\w.]*", re.I)),
)


def declare_family(model_identifier: str) -> str:
    """Return the documented family name for a model identifier.

    Returns "unknown" when no registry entry matches. Callers SHOULD
    extend the registry rather than embed model family logic
    elsewhere.
    """
    if not model_identifier:
        return "unknown"
    text = model_identifier.strip()
    for family, pattern in _FAMILY_REGISTRY:
        if pattern.search(text):
            return family
    return "unknown"


# ---------------------------------------------------------------------------
# G3 self-grounding gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SelfGroundingResult:
    """Verdict of the G3 self-grounding check for a single claim.

    Verdicts:

    - `ok` — writer and verifier are from different families.
    - `family_match` — same family, different version. Permitted but
      flagged for the CBOM `cross_model` field per SPEC-L7-N004.
    - `requires_external_grounding` — writer and verifier are the
      same model identifier. Same-actor self-verification SHALL flag
      this per SPEC-L7-N003 and INV-006.
    """

    verdict: str
    writer_model: str
    verifier_model: str
    writer_family: str
    verifier_family: str
    cross_model: str
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "verdict": self.verdict,
            "writer_model": self.writer_model,
            "verifier_model": self.verifier_model,
            "writer_family": self.writer_family,
            "verifier_family": self.verifier_family,
            "cross_model": self.cross_model,
            "reason": self.reason,
        }


def check_self_grounding(
    writer_model: str,
    verifier_model: Optional[str],
) -> SelfGroundingResult:
    """SPEC-L7-S003/N003/N004 plus INV-006: detect self-grounding.

    Same model identifier between writer and verifier raises the
    `requires_external_grounding` verdict (INV-006). Same family,
    different version flags `family_match` (SPEC-L7-N004) which is
    permitted but recorded in the CBOM. Different families pass.

    A verifier_model of None or empty means no verifier ran; the
    function returns `ok` with `cross_model = "no_verifier"` so the
    caller can still record the absence in the CBOM.

    Parameters
    ----------
    writer_model
        The writer's model identifier.
    verifier_model
        The verifier's model identifier, or None if no verifier ran.

    Returns
    -------
    SelfGroundingResult
    """
    writer = (writer_model or "").strip()
    verifier = (verifier_model or "").strip()

    writer_family = declare_family(writer)
    verifier_family = declare_family(verifier) if verifier else ""

    if not verifier:
        return SelfGroundingResult(
            verdict="ok",
            writer_model=writer,
            verifier_model="",
            writer_family=writer_family,
            verifier_family="",
            cross_model="no_verifier",
            reason="No verifier ran; G3 not triggered.",
        )

    if writer.lower() == verifier.lower():
        return SelfGroundingResult(
            verdict="requires_external_grounding",
            writer_model=writer,
            verifier_model=verifier,
            writer_family=writer_family,
            verifier_family=verifier_family,
            cross_model="self",
            reason=(
                "INV-006 / SPEC-L7-N003: writer and verifier are the same "
                "model identifier; self-grounding SHALL flag "
                "requires_external_grounding."
            ),
        )

    if writer_family != "unknown" and writer_family == verifier_family:
        return SelfGroundingResult(
            verdict="family_match",
            writer_model=writer,
            verifier_model=verifier,
            writer_family=writer_family,
            verifier_family=verifier_family,
            cross_model="family_match",
            reason=(
                "SPEC-L7-N004: writer and verifier belong to the same "
                "model family. Permitted but flagged for the CBOM."
            ),
        )

    return SelfGroundingResult(
        verdict="ok",
        writer_model=writer,
        verifier_model=verifier,
        writer_family=writer_family,
        verifier_family=verifier_family,
        cross_model="family_distinct",
        reason="Writer and verifier are from different model families.",
    )


# ---------------------------------------------------------------------------
# G4 contamination, G5 calibration (NOT BUILT)
# ---------------------------------------------------------------------------

def check_contamination(*_args, **_kwargs):  # pragma: no cover - stub
    """SPEC-L7-R001 G4: NOT BUILT in v0.5.

    A useful G4 implementation requires a documented prompt-injection
    threat model and a labelled corpus of contamination patterns.
    Neither exists yet. v0.5 ships the stub so callers can detect that
    G4 has not been wired and either supply their own check or skip.

    Raises
    ------
    NotImplementedError
    """
    raise NotImplementedError(
        "Gate G4 (contamination) is NOT BUILT in v0.5. Required: a "
        "documented prompt-injection threat model and a labelled "
        "corpus. Tracked as a deferred SHOULD in CHANGELOG."
    )


def check_calibration(*_args, **_kwargs):  # pragma: no cover - stub
    """SPEC-L7-R002 G5: NOT BUILT in v0.5.

    A useful G5 implementation requires the verifier to emit a
    confidence per claim. The offline heuristic verifier emits None
    for confidence on most paths, which makes a Brier score
    meaningless. v0.5 ships the stub; G5 is deferred until the
    verifier surface guarantees a numeric confidence.

    Raises
    ------
    NotImplementedError
    """
    raise NotImplementedError(
        "Gate G5 (calibration) is NOT BUILT in v0.5. Required: a "
        "verifier surface that emits a numeric confidence per claim. "
        "Tracked as a deferred SHOULD in CHANGELOG."
    )
