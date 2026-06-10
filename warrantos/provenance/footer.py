"""provenance.footer: reader-facing override footer for SPEC-L8-S005.

SPEC-L8-S005 normative: a `final-prose` artefact shipped on override
SHALL list its overrides in a reader-facing footer or methodology note,
not only in the audit-facing CBOM. Visibility forces the operator into
reputational commitment.

This module renders a Markdown footer block from a list of HumanOverride
rows. The format is short and readable so it can be appended to any
final-prose artefact without restructuring it.

Stdlib only. Python 3.8 compatible.
"""

from typing import Iterable, List

from warrantos.provenance.overrides import HumanOverride


def render_override_footer(
    overrides: Iterable[HumanOverride],
    heading: str = "Overrides applied",
) -> str:
    """Render a Markdown footer block listing every override on this run.

    SPEC-L8-S005: a final-prose artefact shipped on override SHALL carry
    its override list in a reader-facing footer. This function produces
    that block.

    An empty override list returns the empty string. No empty heading is
    rendered, because SPEC-L8-S005 applies only when an override exists.

    Each row contains:

    - Override id (the human_override row primary key, prefixed `ovr_`)
    - The gate id that was overridden (G1/G2/G3/...) and the failure_class
    - The risk_accepted text
    - The compensating_control text
    - A `single_actor` marker when SPEC-L8-S003 applied

    Parameters
    ----------
    overrides
        Iterable of HumanOverride rows (typically from
        ``provenance.overrides.list_overrides_for_run``).
    heading
        Optional override heading. Default "Overrides applied".

    Returns
    -------
    str
        The Markdown block, or the empty string if no overrides exist.
    """
    rows: List[HumanOverride] = list(overrides)
    if not rows:
        return ""

    lines = ["", "## " + heading.strip(), ""]
    lines.append(
        "The following gate verdicts were overridden by a human reviewer "
        "before this artefact was released. Each entry carries the "
        "rationale and the compensating control on record."
    )
    lines.append("")
    for row in rows:
        lines.extend(_render_one(row))
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")  # one trailing newline-ready blank
    return "\n".join(lines) + "\n"


def _render_one(row: HumanOverride) -> List[str]:
    """Render one HumanOverride as a Markdown list block."""
    marker = " (single-actor; artefact role downgraded)" if row.single_actor else ""
    return [
        "- **Override ovr_%d** on gate **%s** (failure: %s)%s"
        % (row.id, row.gate_id, row.failure_class, marker),
        "  - Risk accepted: %s" % _safe(row.risk_accepted),
        "  - Compensating control: %s" % _safe(row.compensating_control),
        "  - Escalation: %s" % _safe(row.escalation_path_taken),
        "  - Reviewer: %s" % _safe(row.reviewer),
        "  - Recorded: %s" % _safe(row.ts),
    ]


def _safe(text: str) -> str:
    """Squash newlines so a multi-line rationale does not break the list."""
    if not text:
        return ""
    return " ".join(str(text).split())
