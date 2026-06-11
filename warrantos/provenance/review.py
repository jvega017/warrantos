"""Review finding consolidation for WarrantOS review packs.

Findings are grouped into:
- convergent: multiple reviewers or passes identified the same issue key
- distinct: stand-alone actionable findings
- deferred: findings intentionally carried forward for later work

Stdlib only. Python 3.8 compatible.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


_SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass(frozen=True)
class ReviewFinding:
    """A single review finding before consolidation."""

    finding_id: str
    title: str
    detail: str
    severity: str
    location: str
    issue_key: Optional[str] = None
    deferred: bool = False


@dataclass(frozen=True)
class FindingGroup:
    """A consolidated review finding group."""

    issue_key: str
    title: str
    detail: str
    severity: str
    locations: List[str]
    finding_ids: List[str]
    findings: List[ReviewFinding]


@dataclass(frozen=True)
class ReviewConsolidation:
    """Consolidated review findings split by disposition."""

    convergent: List[FindingGroup]
    distinct: List[FindingGroup]
    deferred: List[FindingGroup]


def consolidate_findings(findings: Iterable[ReviewFinding]) -> ReviewConsolidation:
    """Consolidate findings into convergent, distinct, and deferred groups."""
    pending: List[ReviewFinding] = []
    deferred: List[FindingGroup] = []

    for finding in findings:
        if finding.deferred:
            deferred.append(_group_from_findings([finding], finding.issue_key or finding.finding_id))
        else:
            pending.append(finding)

    keyed: Dict[str, List[ReviewFinding]] = {}
    distinct: List[FindingGroup] = []
    key_order: List[str] = []

    for finding in pending:
        if finding.issue_key:
            if finding.issue_key not in keyed:
                keyed[finding.issue_key] = []
                key_order.append(finding.issue_key)
            keyed[finding.issue_key].append(finding)
        else:
            distinct.append(_group_from_findings([finding], finding.finding_id))

    convergent: List[FindingGroup] = []
    for issue_key in key_order:
        group_findings = keyed[issue_key]
        group = _group_from_findings(group_findings, issue_key)
        if len(group_findings) > 1:
            convergent.append(group)
        else:
            distinct.append(group)

    return ReviewConsolidation(
        convergent=convergent,
        distinct=distinct,
        deferred=deferred,
    )


def render_review_markdown(consolidation: ReviewConsolidation) -> str:
    """Render consolidated findings as Markdown."""
    if not (consolidation.convergent or consolidation.distinct or consolidation.deferred):
        return "# Provenance Review\n\nNo findings.\n"

    lines = ["# Provenance Review", ""]
    _append_section(lines, "Convergent", consolidation.convergent)
    _append_section(lines, "Distinct", consolidation.distinct)
    _append_section(lines, "Deferred", consolidation.deferred)
    return "\n".join(lines).rstrip() + "\n"


def _group_from_findings(findings: List[ReviewFinding], issue_key: str) -> FindingGroup:
    first = findings[0]
    return FindingGroup(
        issue_key=issue_key,
        title=first.title,
        detail=first.detail,
        severity=_highest_severity(findings),
        locations=_unique([finding.location for finding in findings]),
        finding_ids=[finding.finding_id for finding in findings],
        findings=list(findings),
    )


def _highest_severity(findings: List[ReviewFinding]) -> str:
    return sorted(
        (finding.severity for finding in findings),
        key=lambda severity: _SEVERITY_RANK.get(severity, 99),
    )[0]


def _unique(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _append_section(lines: List[str], title: str, groups: List[FindingGroup]) -> None:
    lines.append("## " + title)
    lines.append("")
    if not groups:
        lines.append("No findings.")
        lines.append("")
        return

    for group in groups:
        lines.append("- **%s %s**: %s" % (group.severity, group.title, group.detail))
        lines.append("  Locations: " + ", ".join(group.locations))
        lines.append("  Sources: " + ", ".join(group.finding_ids))
    lines.append("")
