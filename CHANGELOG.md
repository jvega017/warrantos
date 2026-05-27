# Changelog

All notable changes to `claude-provenance` are recorded here. The
project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and Semantic Versioning.

## [Unreleased]

### Added — Path X3 (WarrantOS upstream integration leg)

- **CBOM v0.2 schema additions** (SPEC-F-S002, SPEC-L1-S005, §10.3).
  `provenance.cbom.CBOM` carries `actor_identity` (role to identity
  map), `classification_overrides` (list of override rows referencing
  the human_override ledger), and `override_ledger_refs` (list of
  override ids). All three fields default to empty so v0.1 callers
  continue to work unchanged. Schema name remains `warrantos-cbom/v1`
  per INV-007 (additive change only).
- **Structured human override ledger** (SPEC-L8-S002 / SPEC-L8-S003 /
  SPEC-L8-S004). `provenance.overrides.record_override()` writes a
  row to a new `human_override` SQLite table. Empty `risk_accepted`
  or `compensating_control` SHALL block the override at the write
  path; the override does not exist if it cannot be recorded.
  `enforce_single_actor_rule()` implements SPEC-L8-S003: when
  reviewer identity matches the writer-pack actor and the artefact
  role is `final-prose`, the role is downgraded to `draft`.
- **Review-role registry and SPEC-L1-S005 classification gate**.
  `provenance.review_roles.REVIEW_ROLE_REGISTRY` enumerates eight
  canonical review-role agent names (`fresh-critic`,
  `evidence-auditor`, `policy-red-team`, `paper-editor`,
  `codex-rescue`, `policy-debate`, `claim-verify`,
  `rejection-handler`). When `classify_context()` receives a
  `source_agent` in the registry, classification is forced to
  `review_finding` ahead of the rule-based decision tree. This
  closes the Wave A policy-red-team A1 classification-laundering
  attack: a review_finding cannot be silently reclassified to
  `private_reasoning` merely because its text contains a "chain of
  thought" keyword. To override the gate, callers must supply a
  recorded override id via `classify_with_override()`.
- **Reader-facing override footer** (SPEC-L8-S005).
  `provenance.footer.render_override_footer()` emits a Markdown
  block listing every override applied to a run. Empty list returns
  the empty string. Single-actor downgrades carry a visible marker.
- **Integration CLI** (`cli/warrantos_cli.py`). A single command that
  runs Layer 1 classification with SPEC-L1-S005 source_agent gating,
  Layer 7 G1 prose-boundary scan, Layer 7 G2 claim detection with
  optional verifier, and CBOM v0.2 assembly, then emits a four-state
  consolidated verdict (PASS, HOLD, BLOCK, NOT_ASSESSABLE). The
  `NOT_ASSESSABLE` state closes a Codex adversarial-review concern:
  a final-prose artefact cannot certify as PASS without
  `actor_identity` to support the override/identity leg of the
  coupling thesis. Per-run JSON artefacts are written to
  `.warrant/runs/<run_id>/`.
- **MCP server wrapper** (`provenance/mcp_server.py`, Path X4-A).
  Exposes `warrant_check`, `warrant_classify`,
  `warrant_record_override`, and `warrant_get_run` as MCP tools. The
  `mcp` SDK is an optional dependency: the module imports cleanly
  without it; only `run_stdio_server()` raises ImportError with an
  install message. In-process dispatch via `call_tool_in_process()`
  lets callers use the pipeline as a Python API.
- **Shadow-mode observer** (`tools/warrantos-shadow-observe.py`,
  Path X4-B). Read-only observer that runs the warrantos pipeline
  over an already-published brief artefact and appends one
  JSON-line summary per run to a shadow log. Never blocks anything.
  Never modifies any production script. Includes a "NOT enforced"
  note in every row.

### Fixed

- `cli/provenance_cli.py` lacked `sys.path` manipulation, so
  `import provenance.context_admissibility` failed when the CLI was
  invoked as a subprocess; the lazy import caught the
  `ModuleNotFoundError` and emitted "context admissibility module is
  not available." with no output. Added the four-line
  `sys.path.insert` pattern; both `tests/test_context_cli.py`
  failures cleared.
- `tests.test_context_admissibility.test_admissibility_summary_is_stable`
  asserted the v0.1 seven-key dict shape; `admissibility_summary()`
  now emits ten keys (the seven v0.1 keys plus `can_be_seen_by`,
  `cannot_be_seen_by`, `prohibited_use`). Updated the assertion to
  the canonical v0.2 shape.

### Documentation

- `docs/PROBLEM-STACK.md` (in WarrantOS project folder, not yet in
  the public repo) carries the integration thesis: WarrantOS is the
  integration of six diagnosed failure modes from six papers, with
  a cross-cutting set of invariants enforcing the coupling.
  Provenance Ledger, Drift, LOGOS, Borrowed-Counterfactuals, Flagship
  2026, and MAG each contribute one failure mode and one layer.

### Test coverage

- 341 tests, 0 failures, 0 errors at branch tip.
- Coverage added for the v0.2 CBOM fields, override schema, review
  role registry, override footer rendering, full pipeline integration,
  MCP server tool dispatch, and the shadow observer.

### Honest limits carried forward

- The offline heuristic verifier cannot emit `contradicted` by
  construction. The BLOCK-on-contradicted branch fires only when an
  LLM grader is configured via `ANTHROPIC_API_KEY` or a callable
  cross-model backend is supplied.
- Layer 5 writer pack and Layer 6 clean-room generation are NOT
  BUILT. The harness operates over an already-written draft. Layer
  5/6 are a later path.
- Layer 7 G3 (self-grounding), G4 (contamination), and G5
  (calibration) gates are NOT BUILT.
- The SPEC-L1-S006 labelled classifier corpus (N >= 50 per class)
  does not yet exist. SPEC-v0.2 marks this as a SHOULD; promoting to
  SHALL is a v0.3 deliverable.

## [0.3.0] — 2026-05-21

- Cross-model grader (`--grader codex` evaluation-only backend).
- Governance reframe of eval documentation against HANS and ALCE.
- Per-class P/R/F1 over a 60-item labelled corpus.

## [0.2.0]

- Out-of-band verifier with fetch + LLM grading.
- Two-axis detection/verification model.
- Standalone CLI with CI mode.
- Epistemic-debt metric and evidence-matrix export.
- Salience weighting.
- Evaluation harness.

## [0.1.0]

- Heuristic detector with claim extraction.
- SQLite ledger.
- Report and enforce modes.
