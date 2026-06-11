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
from typing import Dict, List, Optional


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

# ---------------------------------------------------------------------------
# G4 contamination scan (starter pattern list)
# ---------------------------------------------------------------------------

# Starter list of prompt-injection patterns. This list is DELIBERATELY
# INCOMPLETE. A production deployment SHALL replace or extend the list
# with a documented threat model and labelled corpus. The list below is
# drawn from publicly known prompt-injection literature (Greshake et al.
# 2023; Liu et al. 2023; Anthropic's prompt-injection guidance) and is
# intended only as a starter so the gate can fire on the most common
# patterns rather than silently passing every input.
_CONTAMINATION_PATTERNS = (
    ("ignore_instructions", re.compile(
        r"\b(?:ignore|disregard)\b[^.]{0,40}\b(?:previous|prior|earlier|all)\b[^.]{0,40}\b(?:instructions?|prompt|rules?)\b",
        re.I,
    )),
    ("you_are_now", re.compile(r"\byou\s+are\s+now\b", re.I)),
    ("system_role_inject", re.compile(r"^\s*system\s*:", re.I | re.M)),
    ("chat_template_open", re.compile(r"<\|im_start\|>|<\|system\|>|\[INST\]|<\|begin_of_text\|>", re.I)),
    ("chat_template_close", re.compile(r"<\|im_end\|>|<\|/system\|>|\[/INST\]|<\|end_of_text\|>", re.I)),
    ("override_role", re.compile(r"\b(?:role\s*[:=]\s*system|act\s+as\s+(?:an?\s+)?admin|developer\s+mode)\b", re.I)),
    ("end_of_prompt_marker", re.compile(r"\b(?:END\s+OF\s+PROMPT|END\s+OF\s+INSTRUCTIONS?)\b", re.I)),
    ("repeat_above", re.compile(r"\brepeat\s+(?:the\s+)?(?:above|previous|earlier)\b[^.]{0,40}\b(?:prompt|instructions?|text)\b", re.I)),
)


@dataclass(frozen=True)
class ContaminationMatch:
    """A single contamination-pattern hit."""

    rule_id: str
    matched_text: str
    line_number: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "matched_text": self.matched_text,
            "line_number": self.line_number,
        }


@dataclass(frozen=True)
class ContaminationResult:
    """SPEC-L7-R001 G4 result.

    Attributes
    ----------
    verdict
        `pass` if no patterns matched; `blocked` if at least one did.
    matches
        List of ContaminationMatch rows.
    corpus_completeness
        Always `starter`. v0.6 ships a starter list only; a production
        deployment SHALL replace or extend with a documented corpus.
    """

    verdict: str
    matches: List[ContaminationMatch]
    corpus_completeness: str = "starter"

    def to_dict(self) -> Dict[str, object]:
        return {
            "verdict": self.verdict,
            "matches": [m.to_dict() for m in self.matches],
            "corpus_completeness": self.corpus_completeness,
            "note": (
                "The contamination pattern list is a starter set. "
                "Production deployments SHALL replace or extend it "
                "with a documented threat model and labelled corpus."
            ),
        }


def check_contamination(text: str) -> ContaminationResult:
    """Scan text for prompt-injection patterns.

    SPEC-L7-R001 G4. Returns `blocked` if any pattern matches;
    otherwise `pass`. The pattern list is a documented starter set;
    callers in production SHALL extend it.
    """
    if not text:
        return ContaminationResult(verdict="pass", matches=[])

    matches: List[ContaminationMatch] = []
    lines = text.splitlines() or [text]
    for line_number, line in enumerate(lines, 1):
        for rule_id, pattern in _CONTAMINATION_PATTERNS:
            for hit in pattern.finditer(line):
                matches.append(ContaminationMatch(
                    rule_id=rule_id,
                    matched_text=hit.group(0)[:120],
                    line_number=line_number,
                ))

    return ContaminationResult(
        verdict="blocked" if matches else "pass",
        matches=matches,
    )


# ---------------------------------------------------------------------------
# G5 calibration (Brier score with explicit coverage)
# ---------------------------------------------------------------------------

# Map verdict labels to a binary "claim was correct" interpretation
# used by Brier scoring. `verified` is treated as true; `contradicted`
# is treated as false. Every other verdict label (`not_addressed`,
# `unverifiable`, `skipped`, `error`) is OUTSIDE the calibration
# universe and is excluded from the score.
_CALIBRATION_TRUE_LABELS = frozenset({"verified"})
_CALIBRATION_FALSE_LABELS = frozenset({"contradicted"})
_CALIBRATION_TYPED_LABELS = _CALIBRATION_TRUE_LABELS | _CALIBRATION_FALSE_LABELS


@dataclass(frozen=True)
class CalibrationResult:
    """SPEC-L7-R002 G5 result.

    Attributes
    ----------
    total
        Total verdict rows considered.
    typed
        Rows with a verdict in {verified, contradicted} (i.e. the
        rows that contribute a ground-truth label).
    with_confidence
        Rows in `typed` that also carry a numeric confidence value.
    coverage
        with_confidence / total. The fraction of all verdicts that
        contribute to the Brier score.
    brier
        Brier score over the rows in `with_confidence`. None when
        with_confidence is 0.
    note
        Honest-disclosure note about the offline-heuristic confidence
        gap.
    """

    total: int
    typed: int
    with_confidence: int
    coverage: float
    brier: Optional[float]
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "total": self.total,
            "typed": self.typed,
            "with_confidence": self.with_confidence,
            "coverage": self.coverage,
            "brier": self.brier,
            "note": self.note,
        }


def _calibration_from_stored(stored: Dict) -> CalibrationResult:
    """Build a CalibrationResult from a stored calibration.json dict.

    The stored artefact is produced by `warrantos calibrate` (see
    cli.warrantos_cli) and carries the grader label, corpus size,
    per-class recall, and a coverage estimate. The Brier-style fields
    on CalibrationResult are populated from the stored summary where
    available; otherwise they fall back to honest zeros/None.

    A stored calibration is recognised by the presence of a
    `coverage_estimate` key (the calibrate command always writes it).
    """
    total = int(stored.get("corpus_size", 0) or 0)
    coverage = float(stored.get("coverage_estimate", 0.0) or 0.0)
    with_confidence = int(round(coverage * total)) if total else 0
    brier = stored.get("brier")
    if brier is not None:
        try:
            brier = float(brier)
        except (TypeError, ValueError):
            brier = None
    note = stored.get("note") or (
        "Loaded from a stored calibration.json produced by "
        "`warrantos calibrate`. Coverage is the honest signal: the offline "
        "heuristic grader emits no confidence, so coverage is typically 0 "
        "and per-class recall is the meaningful calibration measure."
    )
    return CalibrationResult(
        total=total,
        typed=int(stored.get("typed", with_confidence) or with_confidence),
        with_confidence=with_confidence,
        coverage=coverage,
        brier=brier,
        note=note,
    )


def check_calibration(verdicts) -> CalibrationResult:
    """SPEC-L7-R002 G5: compute a Brier score with explicit coverage.

    Accepts EITHER:

    - an iterable of live verdict dicts (each at minimum carrying a
      `verdict` field and optionally a `confidence` field), in which
      case the Brier score is computed at runtime as below; OR
    - a single stored ``calibration.json`` dict (recognised by a
      `coverage_estimate` key) produced by `warrantos calibrate`, in
      which case the result is reconstructed from the stored summary
      (grader, corpus size, per-class recall, coverage estimate).

    The dual input lets a caller either grade live verdict rows or
    surface a previously-computed corpus calibration without re-running
    the eval harness.

    For the live-rows path it computes:

    - `total`: count of all verdicts.
    - `typed`: count of verdicts in {verified, contradicted}; only
      typed rows have a ground-truth label suitable for Brier.
    - `with_confidence`: typed rows that ALSO carry a numeric
      confidence value.
    - `coverage`: with_confidence / total.
    - `brier`: Brier score over `with_confidence` rows. None when
      no rows qualify.

    SPEC-L7-R002 honesty: the offline heuristic verifier emits None
    confidence on most paths and cannot emit `contradicted` by
    construction. Coverage is the honest signal; brier is meaningful
    only when coverage is non-zero. v0.6 returns both so the caller
    can report the gap rather than smooth it away.
    """
    # Stored calibration.json path: a single dict carrying the
    # calibrate summary (recognised by the coverage_estimate key).
    if isinstance(verdicts, dict) and "coverage_estimate" in verdicts:
        return _calibration_from_stored(verdicts)

    rows = list(verdicts) if verdicts else []
    total = len(rows)

    typed_rows = [
        r for r in rows
        if isinstance(r, dict) and r.get("verdict") in _CALIBRATION_TYPED_LABELS
    ]

    scored: List[float] = []
    for row in typed_rows:
        conf = row.get("confidence")
        if isinstance(conf, (int, float)):
            label = 1.0 if row.get("verdict") in _CALIBRATION_TRUE_LABELS else 0.0
            scored.append((float(conf) - label) ** 2)

    coverage = (len(scored) / total) if total else 0.0
    brier = (sum(scored) / len(scored)) if scored else None

    note = (
        "Brier score is meaningful only across the with_confidence subset. "
        "Coverage is the honest signal: when coverage is 0 the verifier "
        "did not emit confidence values, typically because the offline "
        "heuristic returns None on most paths. Production deployments "
        "SHALL use an LLM grader that emits numeric confidence."
    )

    return CalibrationResult(
        total=total,
        typed=len(typed_rows),
        with_confidence=len(scored),
        coverage=coverage,
        brier=brier,
        note=note,
    )
