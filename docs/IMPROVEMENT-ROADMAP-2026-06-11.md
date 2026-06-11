# WarrantOS improvement roadmap — v0.9.1 to a trustworthy v1.0

Prepared 2026-06-11. Grounded in the two structured analyses (incomplete layers; claim/verdict pipeline) and the limits flagged in live testing on Juan's machine.

## BLUF

The single highest-value improvement is closing the claim-detection recall gap: adding the missing decision trigger (must/shall/require) plus five further trigger categories lifts estimated recall from 15-25 per cent to 55-70 per cent of factual assertions, and it fixes a structural bug where salience marks obligations load-bearing but detection never sees them. Pair this immediately with per-profile unsupported-claim thresholds so an audit run with 2 of 2 claims unsupported can never again return a bare PASS. With those two trust limits closed, wire `warrantos check` as a real pre-publish gate for briefs and papers, then complete the four incomplete layers. The trajectory is: trustworthy verdicts (Phase 1), enforced in the live pipeline (Phase 2), then layer completion and grader quality (Phase 3) to reach a defensible v1.0.

## Where it stands

WarrantOS v0.9.1 is installed editable with 605 tests green. Twelve layers report BUILT; G4 and G5 are STARTER (functional stubs in `warrantos/provenance/gates.py`), F-classification and F-retention are NOT_BUILT (zero code), and F-policy, F-integrity, F-compliance and F-metrics are PARTIAL. The pipeline works end to end but two defects undermine trust in its output: detection is coarse (5 syntactic CLAIM_TRIGGERS yielded 2 claims from a 3,394-char policy document) and verdict semantics are misleading (PASS means "no HOLD/BLOCK condition fired", not "claims are supported", and the audit profile suppresses the boundary gate unconditionally). The `warrantos-verify-hook` entry point exists but nothing in the brief or paper pipelines actually calls it; the shadow observer only watches post-publication.

## Phased roadmap

### Phase 1 — restore trust in the verdict (1-2 sessions)

These four changes address the two flagged limits that most undermine trust: detection recall and verdict semantics.

1. **Add the decision trigger to CLAIM_TRIGGERS.** Quick, high impact. Closes the structural misalignment where `salience.py` `_DECISION` scores must/shall/require sentences as load-bearing (0.55) but `extract.py` never detects them, so they silently PASS. Update `warrantos/provenance/extract.py` first, then mirror in `warrantos/hooks/provenance_check.py` (the files carry an explicit mirror comment). Estimated +15-20 points recall on policy prose. Files: `warrantos/provenance/extract.py`, `warrantos/hooks/provenance_check.py`.

2. **Fix audit-profile verdict transparency.** Quick, high impact. Add an unsupported-claims count to the text report regardless of grader verdict, annotate the PASS line when unsupported claims exist (for example "PASS (2 unsupported claims; audit profile boundary suppressed; verify manually)"), and add a `--explain-profile` flag that prints what each profile suppresses. This makes leniency visible without changing thresholds. Files: `warrantos/cli/warrantos_cli.py` (`format_text_report`, `consolidate_verdict`), `warrantos/provenance/context_admissibility.py` (docstring).

3. **Add per-profile unsupported-claim fraction thresholds.** Moderate, high impact. A `_PROFILE_UNSUPPORTED_THRESHOLD` dict in `consolidate_verdict()` (audit 0.0, final-prose 0.0 backstop, paper-full 0.20, brief-light 0.25, methodology 0.40, changelog 1.0) so 2-of-2 unsupported triggers HOLD even when neither claim is load-bearing. Surface the rule that fired in the run report JSON. Files: `warrantos/cli/warrantos_cli.py`, `tests/test_warrantos_cli.py`.

4. **Add five further trigger categories.** Moderate, high impact. Superlative, causal, numeric-approximation, named-body attribution (OECD, ABS, Treasury, ANAO and so on) and empirical comparison, mirrored across both detection files, with salience weights (+0.30 for causal, comparison and body attribution so they become HOLD-eligible when unsupported). Extend `eval/corpus/seed.jsonl` with labelled examples per trigger type. Cumulative recall estimate: +30-40 points. Files: `warrantos/provenance/extract.py`, `warrantos/hooks/provenance_check.py`, `warrantos/provenance/salience.py`, `tests/test_verify.py`, `tests/test_warrantos_cli.py`, `eval/corpus/seed.jsonl`.

### Phase 2 — wire the gate and close the v1.0-blocking layers (1-2 weeks)

5. **Register the hooks and build the gate wrapper.** Moderate, high impact. Register `claude_code_verify_hook.py` under `hooks.Stop` (blocking) and `provenance_check.py` under `hooks.PostToolUse` for Write/Edit on .md/.docx in `~/.claude/settings.json`. Build `tools/warrantos-gate.ps1`: run `warrantos check` on the draft, exit non-zero on non-PASS. Files: `~/.claude/settings.json`, `tools/warrantos-gate.ps1` (new).

6. **Integrate the pre-publish gate into the brief pipeline.** Substantial, high impact. `tools/warrantos-pre-publish-gate.ps1` calls `warrantos check --profile brief-light --ci`, exits non-zero on HOLD/BLOCK/NOT_ASSESSABLE, appends the JSON verdict to `publish-gate-shadow.log`; `publish-brief.ps1` calls it before writing output. This converts the shadow observer from observation to blocking. Files: `tools/warrantos-pre-publish-gate.ps1` (new), `C:/Users/jvega/Claude-Workspace/tools/publish-brief.ps1`, `docs/QUICKSTART.md`.

7. **Implement F-classification.** Moderate, high impact. `warrantos/provenance/classification.py` with a `SensitivityTier` dataclass, a 4-tier default registry matching the CLAUDE.md gate (Public, QPS Official, QPS Sensitive/Protected, Credentials), keyword heuristics for QPS terms (Cabinet, ministerial, legal advice markers), a `SensitivityBlock` gate, and an optional `--sensitivity-check` flag. Update `status.py` to report BUILT. Files: new module, `warrantos/cli/warrantos_cli.py`, `warrantos/provenance/status.py`, `tests/test_classification.py`.

8. **Make G5 calibration meaningful on the heuristic path.** Moderate, medium impact. Add a `warrantos calibrate` subcommand that runs `eval/run_eval.py` and writes `calibration.json` (grader, corpus size, per-class recall, coverage estimate) into `.warrant/`; include it in the warrant bundle; let `check_calibration()` accept either live verdict rows or the stored file. This makes G5 non-trivial without an API key. Files: `warrantos/provenance/gates.py`, `warrantos/cli/warrantos_cli.py`, `warrantos/provenance/warrant_bundle.py`, `eval/run_eval.py`, `warrantos/provenance/status.py`.

9. **Add the [CITE NEEDED] tagging pass.** Moderate, medium impact. Read-only annotation of unsupported load-bearing claims in run artefacts, surfaced as a "suggested tags" section; extend the hook to treat [INFERRED] and [SPECULATIVE] as equivalent tags so labelled inferences stop generating false positives. This wires WarrantOS directly into the fact|inference|recommendation|speculation discipline. Files: `warrantos/cli/warrantos_cli.py`, `warrantos/hooks/provenance_check.py`, `warrantos/provenance/extract.py`.

### Phase 3 — depth and durability (2-4 weeks, lower urgency)

10. **ClaudeCliGrader.** Substantial, medium impact. New grader class in `warrantos/provenance/grade.py` modelled on CodexGrader, invoking `claude --print` as a subprocess; selected by `get_grader()` when `claude` is on PATH and no API key or local URL is set. Enables contradicted verdicts on the Max subscription without API spend, per the subscription-over-API rule. Add `PROVENANCE_GRADER` env override. Files: `warrantos/provenance/grade.py`, `tests/test_grade.py`.

11. **Extend the G4 contamination corpus to policy-domain patterns.** Moderate, medium impact. Legislatively-formatted injections, role-impersonation (Director-General, Minister), classification-laundering, output-override headings; labelled corpus of 20+ items in `eval/corpus/contamination.jsonl`; flip `corpus_completeness` to "domain-extended". Satisfies the SPEC-L7-R001 SHALL. Files: `warrantos/provenance/gates.py`, new corpus file, `tests/test_gates.py`, `warrantos/provenance/status.py`.

12. **Implement F-retention as tombstones.** Moderate, medium impact. `retention_window_days` column plus tombstone table in `schema/provenance.sql`; `warrantos/provenance/retention.py` with set-window, tombstone-run and list-expired functions; a `warrantos retention` subcommand. Tombstone-not-delete preserves the append-only ledger design and satisfies INV-011. Files: schema, new module, CLI, `status.py`, `tests/test_retention.py`.

13. **F-metrics aggregation over the shadow log.** Inference: the analyses identify the gap (no aggregation, trend or alerting over `publish-gate-shadow.log`) without specifying a build; a small weekly aggregation script feeding `calibration.json` is the minimal closure. Effort moderate.

## Completing the incomplete layers

| Layer | Current state | What reaches BUILT | Effort |
|---|---|---|---|
| G4 Safety and contamination | STARTER: 8 hard-coded regexes, no labelled corpus, no FP measurement | Policy-domain pattern extension + 20-item labelled corpus + corpus test (SPEC-L7-R001) | Moderate |
| G5 Evaluation and calibration | STARTER: Brier maths correct but inert (HeuristicGrader emits no confidence) | `warrantos calibrate` writing `calibration.json`, consumed by `check_calibration()` and bundled | Moderate |
| F-classification | NOT_BUILT: zero code | `classification.py` with 4-tier QPS registry, heuristic classifier, SensitivityBlock gate | Moderate |
| F-retention | NOT_BUILT: zero code | Tombstone schema + `retention.py` + CLI subcommand (no hard delete) | Moderate |
| F-policy | PARTIAL: taxonomy in docs and CBOM only | Commit the normative SPEC document; machine-readable role registry (inference: analyses name the gaps, not the build) | Moderate |
| F-integrity | PARTIAL: Merkle, Ed25519 and warrant bundle exist behind optional extra | Scheduled attestation/checkpoint rotation; document the envelope format decision (inference) | Moderate |
| F-compliance | PARTIAL: RFC 2119 language, inline SPEC IDs only | Commit SPEC to repo; automated SPEC-ID conformance check; mapping to ISO 42001 / NIST AI RMF / QPS framework | Substantial |
| F-metrics | PARTIAL: daily shadow-log append only | Aggregation + trend over shadow log, linked to `calibration.json` (inference on mechanism) | Moderate |

## Wiring it into Juan's workflow

Make the gate the path of least resistance, not an extra step:

- **Briefs:** `publish-brief.ps1` calls `warrantos-pre-publish-gate.ps1 --profile brief-light --ci` before writing output. The 0.25 unsupported-fraction threshold tolerates routine date references while catching unsupported statistics. The gate appends every verdict to `publish-gate-shadow.log`, so the existing 07:00 observer becomes the audit trail rather than the control.
- **Papers (SSRN/journal):** run the gate manually with `--profile paper-full` (0.20 threshold) before any export step. The [CITE NEEDED] suggested-tags section gives a ready worklist; tagged [INFERRED]/[SPECULATIVE] sentences do not count as unsupported, so the existing labelling discipline pays for itself.
- **Ministerial and Cabinet outputs:** `--profile final-prose` with its 0.0 backstop, so any unsupported load-bearing claim HOLDs. Inference: profile assignment for ministerial outputs is an extrapolation from the profile list; the analyses specify brief-light and paper-full explicitly.
- **In-session:** register `provenance_check.py` on PostToolUse (Write/Edit, .md/.docx only) as the lightweight tripwire and `claude_code_verify_hook.py` on Stop (blocking) so unverified load-bearing claims hand back before a session ends. Filtering to policy-output extensions keeps code work friction-free.

Anti-friction rules: never gate drafts, only publish steps; HOLD output must always name the offending sentences (the tagging pass provides this); `--explain-profile` makes any surprising verdict self-documenting.

## Publish and adoption

Publish steps (Juan acts, per project memory):

1. Merge `feat/ai-scaffold-residue` (8 local commits, nothing pushed) and push to `jvega017/claude-provenance`.
2. Register the `warrantos` PyPI name (pending-publisher already set).
3. Tag v0.9.1; the release workflow pauses at the PyPI environment reviewer gate; approve it.
4. Verify `pip install warrantos` from a clean venv.

Recommended sequencing decision: ship v0.9.1 to PyPI now as-is, and land Phase 1 as v0.9.2 within the fortnight rather than holding the publish. The detection fixes are additive and the version history then documents the calibration improvement honestly.

Two-week adoption path:

- **Days 1-3:** publish to PyPI; land Phase 1 items 1-3; re-run the 3,394-char test document and confirm claim count rises and the audit PASS now carries the unsupported annotation.
- **Days 4-7:** land item 4 (five triggers); register hooks in shadow mode (log, do not block); run every daily brief through `warrantos check` manually and review verdicts for false-positive HOLDs.
- **Days 8-11:** tune thresholds from the week-one shadow data; flip the brief gate to blocking in `publish-brief.ps1`.
- **Days 12-14:** add F-classification and the paper-full gate to the active paper workflow; write the QUICKSTART section documenting profile selection.

## Risks and non-goals

- **Do not chase 100 per cent recall with regexes.** The analyses estimate the six new categories reach 55-70 per cent; the residual requires LLM-based sentence-level extraction. Do not keep adding fragile patterns past that point; the ClaudeCliGrader path is the correct next instrument.
- **Do not build a compliance product.** F-compliance needs the SPEC committed and a conformance check, not a certified ISO 42001 mapping. A mapping table is documentation, not a feature.
- **Do not add hard deletion.** Tombstones satisfy INV-011; hard delete contradicts the append-only ledger design and would weaken the integrity story.
- **Do not gate drafting.** Blocking applies at publish boundaries only. A gate that fires mid-draft will be disabled within a week and the whole system loses credibility.
- **Do not build dashboards before the data is trustworthy.** F-metrics aggregation waits until Phase 1 detection fixes have generated at least a fortnight of shadow-log data worth aggregating.
- **Risk: false-positive HOLDs after the threshold change.** The audit 0.0 threshold is deliberately strict; if week-one shadow data shows routine briefs HOLDing on benign year references, tune the salience weights before relaxing the threshold. Surface the fired rule in the report (Phase 1 item 3) so tuning is evidence-based.
- **Risk: temp clone fragility.** The analyses note the 03_Projects copy is stale and the working clone fragile; merge and push (publish step 1) before starting Phase 1 edits so no improvement work sits unpushed again.