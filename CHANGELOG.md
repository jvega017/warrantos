# Changelog

All notable changes to `claude-provenance` are recorded here. The
project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and Semantic Versioning.

## [Unreleased]

### Added — v0.7 beta-ready packaging

- **pyproject.toml** with three console entry points: `warrantos`
  (the integration CLI), `provenance` (the legacy CLI), and
  `warrantos-mcp` (the MCP server). Zero required dependencies; the
  `mcp` package is an opt-in extra (`pip install
  "claude-provenance[mcp]"`). Targets Python 3.8 - 3.13. Build status
  marked `4 - Beta`.
- **examples/quickstart-demo/** with `draft.md`, `context.json`,
  `actor.json`, and a README walking through the expected HOLD
  verdict line-by-line. Designed so every layer fires at least once
  in a single invocation.
- **docs/QUICKSTART.md** — install + demo + the four-verdict table +
  the threat-model statement (what WarrantOS does and does NOT
  claim).
- **docs/MCP-CONFIG.md** — exact Claude Code and Claude Desktop
  config snippets, sanity-check instructions, cost-aware defaults,
  and troubleshooting.
- **docs/COST.md** — explicit cost matrix: what runs locally (free)
  vs what consumes Anthropic API credits, the three spend-control
  flags, recommended profiles per use case (CI, daily brief,
  Cabinet brief, academic paper), and order-of-magnitude pricing.
- **Cost-control flags on `warrantos check`**: `--max-verify-claims
  N` caps verifier spend by descending salience; `--salience-min
  FLOAT` filters out low-salience claims before they reach the
  verifier. Both report what was skipped in the new
  `verifier_skipped` field so an auditor can see the trade-off.
- **README quickstart** at the top with `pip install` + demo command
  + pointers to the four new docs. Beta status, Python 3.8+, and
  stdlib-only shields.

### Added — v0.6 deferred-list close-out

- **Layer 7 G3 wired into the warrantos CLI**
  (`cli/warrantos_cli.py`). New `--writer-model` and
  `--verifier-model` flags trigger `check_self_grounding`. The result
  lands in the report's `g3_self_grounding` field. When the verdict
  is `requires_external_grounding` or `family_match`, the reason is
  appended to the verdict reasons list as a `FLAG (G3 informational)`
  annotation. SPEC-L7-N003 says SHALL FLAG, not SHALL BLOCK; G3
  therefore does NOT promote PASS to HOLD/BLOCK.
- **Layer 7 G4 contamination scan** (`provenance.gates.check_contamination`).
  Replaces the v0.5 NotImplementedError stub with a regex scan
  against a documented starter pattern list (ignore-instructions,
  you-are-now, system-role inject, chat-template open/close,
  override-role, end-of-prompt marker, repeat-above). Returns a
  `ContaminationResult` with `verdict` in {pass, blocked}. The list
  is explicitly a `starter` corpus; the result carries a note that
  production deployments SHALL extend it.
- **Layer 7 G5 calibration** (`provenance.gates.check_calibration`).
  Replaces the v0.5 NotImplementedError stub with a Brier-score
  implementation that reports explicit coverage: total verdicts,
  typed rows ({verified, contradicted}), with-confidence rows, and
  the Brier score over the with-confidence subset. When coverage is
  zero (the offline-heuristic case), `brier` is None and the
  honest-disclosure note explains why. SPEC-L7-R002.
- **Layer 6 subprocess isolation**
  (`provenance.clean_room.run_clean_room_subprocess`). Level 2
  conformance for SPEC-L6-R001. Spawns a subprocess with a scrubbed
  environment (PATH, SYSTEMROOT, TEMP, TMP, LANG, LC_ALL, HOME,
  USERPROFILE, PYTHONIOENCODING; everything else is suppressed).
  Delivers the InvocationPlan via stdin as JSON. Returns a
  SubprocessRunResult with exit code, stdout, stderr, timed_out
  flag, and the count of scrubbed-vs-kept env keys. Caller-supplied
  `extra_env_allowlist` is the explicit path for threading a
  credential (e.g. `ANTHROPIC_API_KEY`) through.
- **SPEC-L1-S006 classifier corpus scaffold**
  (`eval/classifier-corpus/seeds.jsonl`,
  `eval/run_classifier_corpus.py`). Seed corpus with one
  representative example per class (N = 1 per class) and a runner
  that reports per-class precision and exits non-zero on regression.
  SPEC-L1-S006 SHOULD level reached for v0.6; v0.3 promotion to
  SHALL still requires N >= 50 per class.

### Still deferred (post-v0.6)

- **Promotion of SPEC-L1-S006 from SHOULD to SHALL**: requires
  authoring N >= 50 labelled examples per class. Not fabricated;
  awaits human authoring.
- **G3 verdict promotion (BLOCK or HOLD)**: SPEC says SHALL FLAG.
  Promoting to BLOCK would require a separate decision and SPEC
  amendment.
- **G4 production pattern list**: the starter set fires on the
  obvious patterns; a production corpus requires red-team review
  and threat-model authoring.
- **G5 LLM-grader confidence wiring**: the heuristic verifier cannot
  emit confidence by construction; using the LLM grader for every
  claim is gated by ANTHROPIC_API_KEY and cost.

### Added — v0.5 follow-ups (Layer 5, Layer 6, Layer 7 G3, docs)

- **Layer 5 clean-room writer pack** (`provenance/writer_pack.py`).
  `compile_writer_pack()` builds the five required sections per SPEC
  §6.2: Clean Brief (derived requirements only; no raw feedback),
  Approved Sources (admitted empirical evidence), Style Rules (from
  style signals), Acceptance Tests (default Layer 7 G1/G2/G3
  coverage), and Banned Residue List (boundary rules promoted from
  validation rules). Enforces SPEC-L4-S001 at the writer entry point:
  any item whose `can_be_seen_by` excludes `clean_room_writer` is
  rejected and the count is reported on the pack so the auditor can
  see how much material was withheld from the writer.
- **Layer 6 clean-room generation (discipline mode)**
  (`provenance/clean_room.py`). `prepare_invocation()` builds an
  `InvocationPlan` from a writer pack and a writer-model identifier.
  Refuses arbitrary context kwargs at the API surface: only
  `writer_pack`, `writer_model`, `writer_role`, `max_tokens`, and
  `temperature` are accepted. Any other key (e.g. `context`,
  `system_prompt`, `feedback`) raises ValueError. This is the
  SPEC-L6-S001 discipline; subprocess isolation (SPEC-L6-R001) is
  deferred to Level 2.
- **Layer 7 G3 self-grounding gate** (`provenance/gates.py`).
  `check_self_grounding(writer_model, verifier_model)` returns a
  `SelfGroundingResult` with verdict in {`ok`, `family_match`,
  `requires_external_grounding`}. Documented model-family registry
  resolves Claude, GPT, Gemini, Llama, Grok, Mistral, and Cohere
  identifiers (SPEC-L7-N004). INV-006 fires when writer and verifier
  identifiers match (case-insensitively). `family_match` is permitted
  per SPEC-L7-N004 but recorded for CBOM visibility.
- **docs/OVERVIEW.md** — a fresh-reader's tour of the repository:
  the eight-layer model, the four governance properties, the one
  command that connects every layer, what is built today, and what
  is explicitly NOT built with the rationale for each.

### Deferred from v0.5 (with rationale)

- **Layer 7 G4 (contamination)**: NOT BUILT. Requires a documented
  prompt-injection threat model and a labelled pattern corpus.
  Neither exists yet. The `check_contamination()` stub raises
  `NotImplementedError` so callers detect the gap rather than receive
  a silent pass.
- **Layer 7 G5 (calibration)**: NOT BUILT. Requires the verifier
  surface to emit a numeric confidence per claim. The offline
  heuristic verifier emits None on most paths, which makes a Brier
  score meaningless. `check_calibration()` raises.
- **Layer 6 subprocess isolation**: NOT BUILT. Discipline mode ships;
  subprocess isolation is Level 2 conformance work.
- **G3 wiring into the consolidated verdict**: BUILT as a callable
  module, NOT WIRED into `cli/warrantos_cli.py`'s consolidated
  verdict. Wiring requires deciding whether `requires_external_grounding`
  should HOLD or BLOCK; SPEC-L7-N003 says SHALL FLAG (not SHALL
  BLOCK), so the prudent default is informational only. The flag is
  available via `provenance.gates.check_self_grounding()`; CLI
  integration is a deliberate next-version decision.
- **SPEC-L1-S006 labelled classifier corpus**: NOT BUILT. Requires
  authored examples per class (N >= 50). Not fabricated. Awaits
  human-authored corpus.

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
