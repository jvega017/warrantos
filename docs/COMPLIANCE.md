# WarrantOS Control Mapping (ISO/IEC 42001, NIST AI RMF, AU/QLD gov)

## Disclaimer (read this first)

This document is a **self-assessment control mapping**, not a certification, an
audit, or a statement of conformance. WarrantOS is a personal-capacity,
open-source reference implementation; it has not been assessed by any
accredited body against ISO/IEC 42001, the NIST AI Risk Management Framework,
or any government assurance scheme.

What this document does:

- It maps the controls WarrantOS **actually enforces in code** (the gates
  G1-G5, the override ledger, the data-classification gate, the
  retention/tombstone path, and the Merkle/attestation integrity surface) to
  the relevant clauses and functions of those frameworks.
- It is explicit about what is **out of scope**: WarrantOS implements a narrow
  slice of an AI management system (output integrity and provenance for a
  drafting workflow), not the organisational governance, risk treatment, data
  management, or lifecycle controls those frameworks require end to end.

What this document does **not** do:

- It does not claim WarrantOS "complies with" or is "certified to" ISO/IEC
  42001 or the NIST AI RMF.
- It does not substitute for an organisation's own management system,
  risk assessment, or assurance process.
- A "covered" or "partial" mark below means the named WarrantOS control
  contributes evidence toward that framework outcome for the drafting workflow
  it governs. It does not mean the framework clause is satisfied at the
  organisational level.

The authoritative description of every control referenced here is the
normative specification at [`docs/SPEC.md`](SPEC.md). Every `SPEC-*` and
`INV-*` identifier below is grep-traceable into `warrantos/` and `tests/`
(see SPEC §8 Traceability). Where this mapping and the code disagree, the code
and `docs/SPEC.md` win.

Coverage legend:

- **Covered**: an enforced WarrantOS control directly produces evidence for
  the named framework outcome, scoped to the drafting/provenance workflow.
- **Partial**: a control exists but is discipline-only, starter-grade, or
  covers only part of the outcome; the gap is named.
- **Out of scope**: the framework outcome is an organisational or lifecycle
  responsibility WarrantOS does not address; the adopter owns it.

---

## 1. WarrantOS enforced controls (the mapping source)

These are the controls this document maps **from**. Each is real code with
tests; none is aspirational. See `docs/SPEC.md` for the normative clause and
`python -m warrantos status` for the live BUILT/PARTIAL state of each.

| Control | Where enforced | Normative clause | What it enforces |
|---|---|---|---|
| G1 Prose boundary | `context_admissibility.scan_prose_boundary()` | SPEC-L7-G1 / SPEC-L7-S004 | Final prose may not carry scaffold/process residue; per-profile boundary. |
| G2 Source & warrant check | `verify.verify_claim()`, graders in `grade.py` | SPEC-L7-G2 | Load-bearing claims must be supported by an admitted source; per-profile unsupported-fraction HOLD thresholds. |
| G3 Non-self-grounding | `gates.check_self_grounding()` | SPEC-L7-S003 / N003 / N004, INV-006 | Flags (informational) when the verifier shares the writer's model family. |
| G4 Safety & contamination | `gates.check_contamination()` | SPEC-L7-R001 | Blocks on prompt-injection / authority-impersonation / classification-laundering patterns (domain-extended, not exhaustive). |
| G5 Evaluation & calibration | `gates.check_calibration()`, `warrantos calibrate` | SPEC-L7-R002 | Brier score with explicit coverage; per-class recall against a labelled corpus; reports coverage even when zero. |
| Human override ledger | `overrides.record_override()`, `enforce_single_actor_rule()`, `render_override_footer()` | SPEC-L8-S002/S003/S004/S005 | Overrides are append-only ledger rows with structured rationale; separation-of-duties flag; reader-facing footer. |
| Data classification gate | `classification.classify_sensitivity()`, `gate_sensitivity()` | F-classification | 4-tier sensitivity gate (Public/Official/Sensitive/Credentials), fail-closed, defaults to Official not Public. |
| Retention / tombstones | `retention.set_window()`, `list_expired()`, `tombstone_run()`, `list_tombstones()` | INV-011 | Append-only retention windows and logical retirement via tombstone; no hard delete (preserves INV-004). |
| Ledger append-only | SQLite BEFORE UPDATE/DELETE triggers, `ledger_write.enable_append_only_triggers()` | INV-004 / SPEC-L2-S002 | Storage-level immutability of ledger rows. |
| Attestation & integrity | `merkle.ledger_root()`, `build_checkpoint()`; `attestation.sign_checkpoint()`; `warrant_bundle.create_warrant()`/`verify_warrant()` | F-integrity | RFC 6962-style Merkle root (stdlib); optional Ed25519 checkpoint signing; fail-closed external verification. |
| Verdict state machine | `verify.consolidate_verdict()` | SPEC §5 | Resolves to PASS / HOLD / BLOCK / NOT_ASSESSABLE; NOT_ASSESSABLE rather than PASS when required metadata (incl. actor identity) is absent. |
| Actor taxonomy / roles | `roles.ACTOR_ROLES`, `validate_actor_identity()`; CBOM `actor_identity` | SPEC-F-S002 | Six machine-readable actor roles; CBOM carries the identity map; runtime validation. |
| Audit logging | SQLite ledger + per-run JSON artefacts + shadow log | F-audit | Cross-run DB, per-run snapshot, observation history. |

---

## 2. ISO/IEC 42001:2023 (AI management systems) mapping

ISO/IEC 42001 specifies requirements for an AI **management system** (AIMS).
WarrantOS is not a management system; it is a technical control set that an
AIMS could adopt as part of its operational controls (broadly the
Annex A control areas concerning system lifecycle, data, and information for
interested parties). The clauses below are mapped at the **control-evidence**
level only. The management-system clauses (4-10: context, leadership, planning,
support, operation, performance evaluation, improvement) are an organisational
responsibility and are marked out of scope.

| ISO/IEC 42001 area (clause / Annex A theme) | WarrantOS control | Coverage | Note |
|---|---|---|---|
| Clauses 4-10 (AIMS: context, leadership, planning, support, operation, evaluation, improvement) | none | Out of scope | These are organisational management-system requirements; WarrantOS provides component evidence only, not the management system. |
| A.6 AI system lifecycle: verification & validation of outputs | G1-G5 gates; `consolidate_verdict()` | Covered | Each publish-boundary run is verified against output-integrity criteria and resolves to an explicit verdict. |
| A.6 lifecycle: operation & monitoring | F-audit (SQLite ledger + per-run JSON + shadow log) | Partial | Per-run and cross-run audit exists; aggregated metrics/trend monitoring (F-metrics) is not built. |
| A.7 Data for AI systems: data quality / provenance of inputs | Context classification (L1), admissibility (L4), provenance ledger (L2) | Covered | Inputs are classified, admissibility-gated, and recorded as append-only ledger rows. |
| A.7 data: data handling / sensitivity controls | `classification.gate_sensitivity()` (4-tier, fail-closed) | Partial | Tier gate is enforced; the keyword heuristics are a documented STARTER set requiring a domain taxonomy. |
| A.8 Information for interested parties: transparency of AI decisions | CBOM (`warrantos-cbom/v1`), `render_override_footer()` | Covered | CBOM records inputs, transforms, claims, and overrides; reader-facing footer surfaces overrides. |
| A.9 Use of the AI system: human oversight / authority | Override ledger (L8): `record_override()`, `enforce_single_actor_rule()` | Covered | Human decisions are recorded with structured rationale and a separation-of-duties flag. |
| A.10 Third-party / supplier considerations: integrity of records | Merkle root, attestation, warrant-bundle verification (F-integrity) | Partial | Tamper-evident integrity and external verification exist; Ed25519 signing is an optional extra and scheduled rotation is not built. |
| Records management / retention | Retention windows + tombstones (INV-011) | Partial | Append-only retention/retirement exists; the adopter still specifies the window and any disposal policy. |
| Risk treatment / impact assessment (A.5) | none | Out of scope | WarrantOS does not perform AI impact or risk assessment; the adopter's AIMS owns this. |

---

## 3. NIST AI Risk Management Framework (AI RMF 1.0) mapping

The NIST AI RMF organises practice into four functions: GOVERN, MAP, MEASURE,
MANAGE. WarrantOS contributes most directly to MEASURE (it measures output
integrity at the publish boundary) and to parts of MANAGE (human override,
retention). GOVERN is largely organisational and is mapped as out of scope
except where a concrete WarrantOS artefact provides evidence.

| AI RMF function / category | WarrantOS control | Coverage | Note |
|---|---|---|---|
| GOVERN 1: policies, processes, accountability | `docs/SPEC.md` (normative, RFC 2119); `roles` taxonomy | Partial | A normative spec and a six-role actor taxonomy exist; organisational accountability structures are out of scope. |
| GOVERN: roles & responsibilities | `roles.ACTOR_ROLES`, `validate_actor_identity()`; CBOM `actor_identity` | Covered | Six machine-readable roles; runtime validation; carried per run in the CBOM. |
| GOVERN: risk management culture/oversight | none | Out of scope | Organisational responsibility. |
| MAP 1-5: context, categorisation of inputs | L1 context classification (11 classes); L4 admissibility | Covered | Inputs are categorised and admissibility-gated before they reach the writer. |
| MAP: impact characterisation | none | Out of scope | WarrantOS does not characterise downstream AI impact. |
| MEASURE 2: evaluation for trustworthiness | G2 source/warrant, G5 calibration (`check_calibration()`, `warrantos calibrate`) | Covered | Claims are verified against admitted sources; calibration reports Brier-with-coverage and per-class recall against a labelled corpus. |
| MEASURE 2: safety / security / resilience | G4 contamination (`check_contamination()`) | Partial | Prompt-injection / impersonation / classification-laundering patterns are blocked; the corpus is domain-extended but not exhaustive. |
| MEASURE: bias / fairness | none | Out of scope | Not addressed; this is a fact-support and integrity tool, not a fairness evaluator. |
| MEASURE: accountability & transparency | CBOM; `render_override_footer()`; per-run JSON artefacts | Covered | Every run emits a traceable bill of materials and a reader-facing override footer. |
| MANAGE 1: risk response / human oversight | Override ledger (L8): structured rationale + SoD flag | Covered | Risk acceptance is an append-only ledger row requiring `risk_accepted` and `compensating_control`. |
| MANAGE 4: documentation, monitoring, recovery | F-audit; retention/tombstones (INV-011); Merkle/attestation | Partial | Tamper-evident records and append-only retention exist; aggregated monitoring (F-metrics) and recovery procedures are out of scope / not built. |
| MANAGE: self-grounding / model-independence risk | G3 (`check_self_grounding()`, INV-006) | Partial | Same-family writer/verifier is flagged (informational), not blocked, per SPEC-L7-N003. |

---

## 4. Australian / Queensland government AI governance relevance

This is a relevance note, not a conformance claim. WarrantOS is developed in a
personal capacity and is not a Queensland Government product.

- **AU Government AI policies (e.g. the Commonwealth policy for responsible use
  of AI in government, and the National framework for the assurance of AI in
  government).** These emphasise transparency, accountability, human oversight,
  and record-keeping. WarrantOS's CBOM (transparency), override ledger with
  separation-of-duties (accountability and human oversight), and append-only
  audit + retention (record-keeping) provide concrete control evidence for the
  drafting workflow they govern. They do not satisfy the policies, which apply
  at the agency and use-case level. *[CITE NEEDED: adopters should cite the
  specific current AU/QLD policy version applicable to their use case; this
  document does not assert clause-level conformance.]*
- **Queensland information-handling and classification.** The
  `classification` gate's default tiers (Public / Official / Sensitive /
  Credentials, defaulting to Official) align in spirit with a tiered
  information-security posture. The keyword heuristics are a documented STARTER
  set and SHALL be extended with the adopter's own classification taxonomy
  before any reliance; they are not a substitute for an agency information
  security classification framework.
- **Records and provenance.** The append-only ledger (INV-004) and
  tombstone-based retention (INV-011, no hard delete) support a defensible
  record of how an output was produced and decided. Disposal authorities and
  retention schedules remain the adopter's responsibility.

The honest summary for a government adopter: WarrantOS can supply
provenance, output-integrity, and human-oversight **evidence** that feeds an
agency's existing AI assurance and records obligations. It does not discharge
those obligations and is not certified against any of them.

---

## 5. Honest ceiling for this control

The honest ceiling for the F-compliance foundation row is a **committed
normative specification plus this documented control mapping**, both
grep-traceable to enforced code. That is what is in scope and what is built.

Anything beyond that: accredited certification to ISO/IEC 42001, a third-party
NIST AI RMF profile assessment, or a government assurance sign-off: is
explicitly **not** claimed and would require an external assessor and an
organisational management system that WarrantOS, as a single-purpose technical
library, does not provide. Per the project roadmap: a mapping table is
documentation, not a compliance product, and WarrantOS does not build a
compliance product.
