# WarrantOS Normative Specification (claude-provenance reference implementation)

Version: v0.9 (matches the `claude-provenance` reference implementation at
this tag). This document is the normative specification referenced by the
inline `SPEC-*` and `INV-*` identifiers in the codebase and tests.

## Status of this document

This SPEC is grounded in what the `claude-provenance` reference
implementation actually enforces at this version. It is deliberately a
specification of the working subset, not of the full WarrantOS vision.
Where a requirement is enforced in code with test coverage and runtime
effect, it is stated as a SHALL. Where the code implements a softer
discipline or a documented starter, the keyword is SHOULD or MAY and the
gap is named. No requirement in this document describes a capability the
code does not implement.

## 1. Conformance language (RFC 2119)

The key words **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT** and
**MAY** in this document are to be interpreted as described in RFC 2119.
A deployment conforms to a given `SPEC-*` clause when the named code path
is present and exercised; conformance to a clause keyed to an optional
extra (for example Ed25519 attestation) requires that extra to be
installed.

## 2. Actor taxonomy (six roles)

WarrantOS records work against six accountable **actor roles**. The CBOM
`actor_identity` map (see §6) is keyed on these six `role_id` strings.
The machine-readable registry is `warrantos.provenance.roles`
(`registry_to_dict()` emits schema `warrantos-roles/v1`).

| `role_id` | Title | Layer | Accountable for |
|---|---|---|---|
| `context_classifier` | Context Classifier | L1 | Classifying every incoming context item and applying review-role gating. |
| `insight_compiler` | Applied Insight Compiler | L3 | Transforming admitted process material into derived requirements and persisting the transform. |
| `source_curator` | Source Curator | L4 | Deciding which admitted items are approved sources and which actors may see each item. |
| `clean_room_writer` | Clean-Room Writer | L5/L6 | Generating the artefact from the writer pack alone, in discipline or subprocess isolation. |
| `reviewer_qa` | Reviewer / QA | L7/L8 | Running the output integrity gates and recording the human decision. |
| `auditor` | Auditor | F-audit | Reading the append-only ledger, CBOM and footer after the fact; never writing runtime artefacts. |

**SPEC-F-S002**: A CBOM produced for a final-prose run SHALL carry an
`actor_identity` entry for each of the six roles above. Each identity
value SHALL be a non-empty string (a user name, API key id, model
identifier, or a tuple thereof). The runtime check is
`roles.validate_actor_identity()`.

These six **actor roles** are distinct from the finer-grained per-item
**viewer identities** used inside the Layer 4 admissibility flags
(`can_be_seen_by` / `cannot_be_seen_by`), which include additional
internal strings (`ledger_writer`, `boundary_gate`, `final_writer`,
`semantic_reviewer`, `revision_planner`). The viewer set is descriptive,
not normative; it is enumerated in `roles.VIEWER_IDENTITIES` so the two
vocabularies are not conflated.

## 3. Invariants (INV-*)

Invariants are properties that SHALL hold across all runs.

### INV-004: Ledger append-only

The ledger tables SHALL be append-only at the storage layer. No row in
an append-only table SHALL be updated or deleted. Enforcement is via
SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers that `RAISE(ABORT)`,
installed by `ledger_write.enable_append_only_triggers()` and by the
`human_override` table creation in `overrides.py`. The append-only
tables are: `human_override`, `context_transform`, `provenance_run`,
`provenance_claim`, `provenance_verification`, `context_item`,
`cbom_run`, `review_finding`, `prose_boundary_violation`. Logical
retirement of a run is by appended tombstone, never by delete (see
INV-011).

### INV-006: No self-grounding promotion

A claim SHALL NOT be promoted to `verified` on the strength of a verifier
that shares the writer's model identity. When `writer_model` equals
`verifier_model`, `gates.check_self_grounding()` SHALL return the
`requires_external_grounding` verdict.

### INV-007: CBOM schema stability

The CBOM schema name SHALL remain `warrantos-cbom/v1`. Schema changes
SHALL be additive only (new optional fields with empty defaults); a
change that would break a v0.1 reader SHALL NOT be made under this schema
name.

### INV-011: Retention by append-only tombstone

Retiring a run on retention-window expiry SHALL append a tombstone row
and SHALL NOT hard-delete any ledger row. Implemented in `retention.py`
(`tombstone_run()`, `list_tombstones()`); preserves INV-004.

## 4. Layer requirements

### Layer 1: Context Classification

**SPEC-L1-S005** (review-role gating): A `review_finding`-shaped input
originating from an agent in the documented review-role registry
(`review_roles.REVIEW_ROLE_REGISTRY`) SHALL NOT be silently reclassified
to `private_reasoning` or `user_feedback`. The authoritative signal is
the caller's `source_agent` argument; text heuristics are a best-effort
secondary signal requiring two or more signals to fire. Any deviation
from the default classifier verdict SHALL be recorded as a
`ClassificationOverrideRecord` pointing to a `human_override` ledger row
with a non-empty `override_id` (`classify_with_override()`).

**SPEC-L1-S006** (classifier corpus): The rule-based classifier SHOULD be
exercised against a labelled corpus. The reference implementation ships
such a corpus test (`tests/test_classifier_corpus.py`); the rule set is
inspectable and intentionally not a learned model.

### Layer 2: Provenance Ledger

**SPEC-L2-S002** (append-only ledger rows): Every classified context
item, transform, and human override SHALL be persisted as an append-only
row. This clause is the storage-layer expression of INV-004 and is
enforced by the same SQLite triggers. The override-ledger write path
(`overrides.record_override()`) SHALL refuse a row that violates the
structured-rationale rule (see SPEC-L8-S004).

### Layer 3: Applied Insight Compiler

**SPEC-L3-N001** (transform persistence): Every transformation of process
material into a derived requirement SHALL write a ledger row recording
the transform (`ledger_write.persist_context_transform()`). Raw process
text SHALL NOT reach Layer 5; only the derived requirement reaches the
writer pack.

### Layer 4: Context Admissibility

**SPEC-L4-S001** (writer admissibility): An item whose admissibility
flags exclude `clean_room_writer` SHALL NOT appear in the writer pack.
The decision rule (`writer_pack._admissible_to_writer()`): reject if
`cannot_be_seen_by` lists `clean_room_writer`; reject if `can_be_seen_by`
is non-empty and omits `clean_room_writer`; reject if the ledger bucket
is `excluded`; otherwise admit. The count of excluded items SHALL be
reported on the pack.

**SPEC-L4-S004** (synthesised judgement is derived-only): A
`synthesised_judgement` item SHALL be admitted to the writer pack only as
a derived requirement, never verbatim (`writer_pack.compile_writer_pack()`).

### Layer 5: Clean-Room Writer Pack

The writer pack SHALL contain exactly five sections (Clean Brief,
Approved Sources, Style Rules, Acceptance Tests, Banned Residue List) and
SHALL NOT contain raw feedback, conversation history, prior failed
drafts, tool traces, or process notes. Schema is
`warrantos-writer-pack/v1`. (Section structure enforced by the
`WriterPack` dataclass; the exclusion of raw process material is enforced
by SPEC-L4-S001 at the entry point.)

### Layer 6: Clean-Room Generation

WarrantOS SHALL NOT call any LLM itself; the caller invokes their writer
model through the returned `InvocationPlan`.

**SPEC-L6-S001** (discipline mode, Level 1): `clean_room.prepare_invocation()`
SHALL refuse arbitrary context kwargs and SHALL present only the writer
pack to the writer entry point.

**SPEC-L6-R001** (subprocess isolation, Level 2):
`clean_room.run_clean_room_subprocess()` SHALL run the writer in a
separate process so out-of-band context cannot leak through shared
in-process state.

### Layer 7: Output Integrity Gates

**SPEC-L7-G1 / SPEC-L7-S004** (prose boundary): `scan_prose_boundary()`
SHALL flag process-to-prose leakage and AI-scaffold residue under a named
profile. SHALL-strength lexical rules (`final-prose`, `brief-light`,
`paper-full`) cover process narration and AI self-reference. The
`prompt-template`, `audit`, `methodology`, `consultation_report` and
`changelog` profiles deliberately suppress the lexical gate; the
structural-narration SHOULD path (SPEC-L7-S004) is documented as NOT
implemented at this version and the profile retains it for a future
release.

**SPEC-L7-S003 / SPEC-L7-N003 / SPEC-L7-N004** (self-grounding): Same
model identity between writer and verifier SHALL flag
`requires_external_grounding` (INV-006). Same model family, different
version SHALL be recorded as `cross_model = family_match` in the CBOM
(SPEC-L7-N004); this is permitted but flagged. The grader SHOULD belong
to a different model family per the documented `_FAMILY_REGISTRY`. The
flag is informational (FLAG, not BLOCK) per SPEC-L7-N003.

**SPEC-L7-R001** (G4 contamination): `check_contamination()` SHALL return
`blocked` if any prompt-injection pattern matches, otherwise `pass`. The
pattern list is documented as domain-extended (generic starter set plus
policy-domain patterns, exercised by `eval/corpus/contamination.jsonl`)
and is NOT exhaustive; production deployments SHOULD extend it against
their own documented threat model.

**SPEC-L7-R002** (G5 calibration): `check_calibration()` SHALL compute a
Brier score with explicit coverage and SHALL report coverage even when it
is zero, rather than smoothing the gap away. The offline heuristic grader
emits no confidence, so coverage is typically 0 and per-class recall is
the meaningful measure until an LLM grader supplies numeric confidence.

### Layer 8: Human Review and Decision Authority

**SPEC-L8-S002** (overrides as ledger rows): Every human override SHALL
be recorded as an append-only `human_override` ledger row, not as free
text.

**SPEC-L8-S003** (separation of duties): When an override is recorded,
`enforce_single_actor_rule()` SHALL flag the case where the reviewer and
writer are the same actor (`single_actor = 1`).

**SPEC-L8-S004** (structured rationale): An override write SHALL be
refused if `risk_accepted` or `compensating_control` is empty. This is a
write-path enforcement, not a discipline rule (`record_override()`).

**SPEC-L8-S005** (reader-facing footer): `render_override_footer()` SHALL
emit a reader-facing footer that surfaces every recorded override for the
artefact.

## 5. Verdict states

A run consolidates to exactly one of four states: `PASS` (ship), `HOLD`
(cite or downgrade a load-bearing claim), `BLOCK` (rewrite), or
`NOT_ASSESSABLE` (required metadata, including actor identity, is
missing). A run SHALL resolve to `NOT_ASSESSABLE` rather than `PASS` when
the metadata required to certify is absent.

## 6. CBOM requirements

A CBOM SHALL carry: context inputs (admitted and blocked), transformations,
claims and their supporting material, review findings, the `actor_identity`
map (SPEC-F-S002, six roles), classification overrides (SPEC-L1-S005), and
override ledger references. Schema is `warrantos-cbom/v1` (INV-007,
additive only). A transformation or claim SHALL NOT reference an unknown
or blocked context input.

## 7. Conformance levels

- **Level 1 (discipline)**: SPEC-L6-S001 discipline mode plus all SHALL
  clauses above that do not require a subprocess or an optional extra.
- **Level 2 (isolation)**: Level 1 plus SPEC-L6-R001 subprocess isolation.
- **Attestation**: cryptographic checkpoint signing requires the optional
  `[attestation]` extra (Ed25519); stdlib Merkle integrity and fail-closed
  `.warrant` verification need no key.

## 8. Traceability

Every `SPEC-*` and `INV-*` identifier in this document appears as an
inline reference in the modules and tests it governs. The mapping is the
grep surface: searching `warrantos/` and `tests/` for an identifier
returns the code path that enforces it. The machine-readable role
registry (`warrantos.provenance.roles`) is the runtime counterpart to §2.
