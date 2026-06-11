"""provenance.metrics: aggregate the shadow-observation log into metrics.

The shadow observer (`tools/warrantos-shadow-observe.py`) appends one
JSON-line per run to a shadow log (default
`08_Outputs/publish-gate-shadow.log`). Each line is a snapshot of a
single observation, never aggregated. This module closes the
F-metrics gap: it reads that JSON-lines log and computes a compact,
honest aggregate:

- verdict distribution (count of PASS / HOLD / BLOCK / etc.);
- the unsupported-claim rate over the whole window AND split into an
  earlier and a later half so a direction of travel can be reported;
- a simple trend label (improving / worsening / stable / insufficient)
  derived from the change in unsupported-claim rate between the two
  halves;
- the observation window (first and last timestamp, number of observed
  rows, number of non-observed rows such as observer_error /
  no_brief_found).

It can write the aggregate to `.warrant/metrics.json` and produce a
small dict suitable for feeding the unsupported-claim signal into the
G5 calibration surface (`provenance.gates.check_calibration`).

Design rules (this is an integrity tool):

- A missing or empty log is NOT an error. It produces an aggregate
  with `observed=0` and `trend="insufficient_data"`, and the writer
  still emits a valid metrics.json. No row is fabricated.
- Malformed JSON lines are counted (`malformed_lines`) and skipped,
  never guessed at.
- Only rows the observer marked `shadow_status == "observed"`
  contribute to verdict/claim metrics. Rows with no claim counts are
  excluded from the unsupported-claim rate (they cannot contribute a
  denominator) but are still counted in `observed`.

Stdlib only. Python 3.8 compatible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Trend is reported only when both halves carry a non-zero claim
# denominator AND the change in unsupported rate exceeds this band.
# Below the band the direction of travel is reported as "stable" to
# avoid over-reading noise in a short observation window.
_TREND_EPSILON = 0.05

# Minimum number of claim-bearing observed rows before a trend is
# computed at all. With fewer rows the split into halves is not
# meaningful and the trend is "insufficient_data".
_MIN_ROWS_FOR_TREND = 4


@dataclass(frozen=True)
class ShadowMetrics:
    """Aggregate of a shadow-observation log.

    Attributes
    ----------
    total_lines
        Every line read from the log (observed + non-observed +
        malformed).
    observed
        Rows with shadow_status == "observed".
    non_observed
        Rows with a shadow_status other than "observed" (e.g.
        observer_error, no_brief_found), broken down in
        `non_observed_by_status`.
    malformed_lines
        Lines that did not parse as JSON objects.
    verdict_distribution
        Count of each consolidated `verdict` value across observed
        rows (e.g. {"PASS": 9, "HOLD": 2}).
    claims_detected_total / claims_supported_total
        Summed across observed rows that carry integer claim counts.
    unsupported_rate
        (detected - supported) / detected across the whole window.
        None when no claim-bearing observed row exists.
    unsupported_rate_earlier / unsupported_rate_later
        The same rate computed over the earlier and later half of the
        claim-bearing observed rows (split by chronological order).
        None when a half has no claim denominator.
    trend
        One of "improving", "worsening", "stable", "insufficient_data".
    window_start / window_end
        First and last `ts` seen on an observed row (ISO-8601 strings),
        or None.
    note
        Honest-disclosure note about what the aggregate does and does
        not claim.
    """

    total_lines: int
    observed: int
    non_observed: int
    malformed_lines: int
    non_observed_by_status: Dict[str, int]
    verdict_distribution: Dict[str, int]
    claims_detected_total: int
    claims_supported_total: int
    unsupported_rate: Optional[float]
    unsupported_rate_earlier: Optional[float]
    unsupported_rate_later: Optional[float]
    trend: str
    window_start: Optional[str]
    window_end: Optional[str]
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_lines": self.total_lines,
            "observed": self.observed,
            "non_observed": self.non_observed,
            "malformed_lines": self.malformed_lines,
            "non_observed_by_status": dict(self.non_observed_by_status),
            "verdict_distribution": dict(self.verdict_distribution),
            "claims_detected_total": self.claims_detected_total,
            "claims_supported_total": self.claims_supported_total,
            "unsupported_rate": self.unsupported_rate,
            "unsupported_rate_earlier": self.unsupported_rate_earlier,
            "unsupported_rate_later": self.unsupported_rate_later,
            "trend": self.trend,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "note": self.note,
        }


def _iter_rows(log_path: Path) -> List[Dict[str, Any]]:
    """Read the log and return parsed JSON objects.

    Lines that do not parse as a JSON object are collected separately
    by the caller via the `_MALFORMED` sentinel. Here we return a list
    where each element is either a dict (parsed object) or the
    `_MALFORMED` sentinel for a line that failed to parse.

    A missing log yields an empty list (not an error): the absence of
    observations is a valid, honestly-reported state.
    """
    rows: List[Any] = []
    if not log_path.is_file():
        return rows
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except (ValueError, json.JSONDecodeError):
                rows.append(_MALFORMED)
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                # A JSON value that is not an object (e.g. a bare list or
                # number) is not a valid shadow row.
                rows.append(_MALFORMED)
    return rows


# Sentinel for a line that failed to parse as a JSON object.
_MALFORMED = object()


def _claim_counts(row: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Return {detected, supported} for a row, or None if absent.

    Only integer counts are accepted. A row missing either count, or
    carrying a non-integer / negative value, contributes no denominator
    and is excluded from the unsupported-claim rate.
    """
    detected = row.get("claims_detected")
    supported = row.get("claims_supported")
    if not isinstance(detected, int) or not isinstance(supported, int):
        return None
    if detected < 0 or supported < 0 or supported > detected:
        return None
    return {"detected": detected, "supported": supported}


def _rate(detected: int, supported: int) -> Optional[float]:
    if detected <= 0:
        return None
    return round((detected - supported) / detected, 4)


def aggregate_shadow_log(
    log_path: Union[str, Path],
) -> ShadowMetrics:
    """Aggregate a shadow-observation JSONL log into a ShadowMetrics.

    Handles a missing or empty log gracefully: returns an aggregate
    with `observed=0` and `trend="insufficient_data"`.
    """
    path = Path(log_path)
    parsed = _iter_rows(path)

    total_lines = len(parsed)
    malformed_lines = sum(1 for r in parsed if r is _MALFORMED)
    dict_rows: List[Dict[str, Any]] = [r for r in parsed if r is not _MALFORMED]

    observed_rows: List[Dict[str, Any]] = []
    non_observed_by_status: Dict[str, int] = {}
    for row in dict_rows:
        status = row.get("shadow_status")
        if status == "observed":
            observed_rows.append(row)
        else:
            key = str(status) if status is not None else "unknown"
            non_observed_by_status[key] = non_observed_by_status.get(key, 0) + 1

    observed = len(observed_rows)
    non_observed = len(dict_rows) - observed

    # --- verdict distribution (observed rows only) ---
    verdict_distribution: Dict[str, int] = {}
    for row in observed_rows:
        verdict = row.get("verdict")
        if verdict is None:
            continue
        key = str(verdict)
        verdict_distribution[key] = verdict_distribution.get(key, 0) + 1

    # --- window (observed rows that carry a ts) ---
    timestamps = [
        row["ts"] for row in observed_rows
        if isinstance(row.get("ts"), str)
    ]
    # The observer writes ISO-8601 Zulu timestamps, which sort
    # lexicographically in chronological order.
    timestamps_sorted = sorted(timestamps)
    window_start = timestamps_sorted[0] if timestamps_sorted else None
    window_end = timestamps_sorted[-1] if timestamps_sorted else None

    # --- unsupported-claim rate, whole window + halves ---
    # Build the claim-bearing rows in chronological order. Rows without
    # a ts are ordered after timed rows (stable), so the split stays
    # deterministic.
    claim_rows = [
        (row.get("ts") or "", counts)
        for row in observed_rows
        for counts in (_claim_counts(row),)
        if counts is not None
    ]
    claim_rows.sort(key=lambda pair: pair[0])

    detected_total = sum(c["detected"] for _ts, c in claim_rows)
    supported_total = sum(c["supported"] for _ts, c in claim_rows)
    unsupported_rate = _rate(detected_total, supported_total)

    unsupported_rate_earlier: Optional[float] = None
    unsupported_rate_later: Optional[float] = None
    trend = "insufficient_data"

    if len(claim_rows) >= _MIN_ROWS_FOR_TREND:
        mid = len(claim_rows) // 2
        earlier = claim_rows[:mid]
        later = claim_rows[mid:]
        e_det = sum(c["detected"] for _ts, c in earlier)
        e_sup = sum(c["supported"] for _ts, c in earlier)
        l_det = sum(c["detected"] for _ts, c in later)
        l_sup = sum(c["supported"] for _ts, c in later)
        unsupported_rate_earlier = _rate(e_det, e_sup)
        unsupported_rate_later = _rate(l_det, l_sup)
        if (
            unsupported_rate_earlier is not None
            and unsupported_rate_later is not None
        ):
            delta = unsupported_rate_later - unsupported_rate_earlier
            if delta <= -_TREND_EPSILON:
                # Unsupported rate fell over time: fewer unsupported
                # claims in recent runs is an improvement.
                trend = "improving"
            elif delta >= _TREND_EPSILON:
                trend = "worsening"
            else:
                trend = "stable"

    note = (
        "Aggregate of the shadow-observation log. Verdict and claim "
        "metrics are computed only from rows the observer marked "
        "shadow_status=observed; non-observed rows (observer_error, "
        "no_brief_found) are counted but excluded from the rates. "
        "'trend' compares the unsupported-claim rate of the earlier "
        "and later halves of the claim-bearing observed rows; a change "
        "smaller than %.2f is reported as 'stable', and fewer than %d "
        "claim-bearing rows yields 'insufficient_data'. The shadow log "
        "is observation-only and is NOT an enforcement record."
        % (_TREND_EPSILON, _MIN_ROWS_FOR_TREND)
    )

    return ShadowMetrics(
        total_lines=total_lines,
        observed=observed,
        non_observed=non_observed,
        malformed_lines=malformed_lines,
        non_observed_by_status=non_observed_by_status,
        verdict_distribution=verdict_distribution,
        claims_detected_total=detected_total,
        claims_supported_total=supported_total,
        unsupported_rate=unsupported_rate,
        unsupported_rate_earlier=unsupported_rate_earlier,
        unsupported_rate_later=unsupported_rate_later,
        trend=trend,
        window_start=window_start,
        window_end=window_end,
        note=note,
    )


def write_metrics_json(
    metrics: ShadowMetrics,
    out_path: Union[str, Path],
) -> Path:
    """Write the aggregate to a metrics.json file.

    Creates the parent directory if needed. Returns the resolved path
    written. The caller is responsible for path containment (the CLI
    confines this under .warrant/ via pathguard.resolve_under).
    """
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metrics.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def calibration_supplement(metrics: ShadowMetrics) -> Dict[str, Any]:
    """Return a small dict linking the shadow aggregate to G5.

    `provenance.gates.check_calibration` measures grader calibration
    against a labelled corpus. The shadow log measures something
    different but complementary: the observed unsupported-claim rate on
    real published artefacts over time. This helper exposes that signal
    in a shape a caller can attach alongside a CalibrationResult so the
    two surfaces sit together, WITHOUT pretending the shadow rate is a
    Brier-style confidence calibration.

    The returned dict is intentionally minimal and honest: it carries
    the observed unsupported-claim rate, the trend, and the sample
    size, plus a note that this is an operational monitoring signal,
    not a corpus calibration.
    """
    return {
        "source": "shadow_log",
        "observed_unsupported_rate": metrics.unsupported_rate,
        "unsupported_rate_trend": metrics.trend,
        "unsupported_rate_earlier": metrics.unsupported_rate_earlier,
        "unsupported_rate_later": metrics.unsupported_rate_later,
        "observed_rows": metrics.observed,
        "claims_detected_total": metrics.claims_detected_total,
        "note": (
            "Operational monitoring signal from the shadow log, NOT a "
            "corpus calibration. It reports the unsupported-claim rate "
            "observed on real published artefacts and its direction of "
            "travel; it does not measure grader confidence calibration "
            "(that is check_calibration over the labelled eval corpus)."
        ),
    }
