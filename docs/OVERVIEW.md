# What is in this repository

A short, plain-language tour of `claude-provenance` for a reader who
has just landed on the repository and wants to know what it actually
does, in what order, and what is and is not built.

## The one-sentence pitch

`claude-provenance` is the reference implementation of WarrantOS: a
governance harness that wraps AI-assisted writing so that final
artefacts ship clean prose, and a separate audit ledger carries the
sources, the feedback, the review history, the transformations, and
the overrides that produced them.

## The problem it addresses

AI-assisted writing fails in three predictable ways at the same time:

1. **Epistemic failure.** The model states a fact, no citation
   accompanies it, no one checks, the artefact ships.
2. **Context laundering.** Feedback, process history, or chain-of-
   thought leaks into the final artefact verbatim ("based on your
   feedback this is now more commercial") instead of being applied
   silently.
3. **Accountability gap.** When a control fires and an operator
   overrides it, the override is recorded as free text ("approved"),
   which lets the override become a self-written permission slip with
   no traceable rationale.

Each failure mode is the subject of a separate working paper. The
WarrantOS coupling thesis is that they are not independent: fixing
the citation layer without the context-laundering layer leaves the
same attack surface, just relocated.

## What is in the repository, in order

`claude-provenance` is organised as eight layers plus a foundation
row. The eight layers map directly to the SPEC sections under
`docs/STACK.md`.

| # | Layer | What it does | Module |
|---|---|---|---|
| 1 | Context classification | Tags every incoming chunk into one of eleven canonical classes (`empirical_evidence`, `instruction`, `style_signal`, `user_feedback`, `prior_artefact`, `process_history`, `operational_trace`, `review_finding`, `validation_rule`, `synthesised_judgement`, `private_reasoning`) | `provenance/context_admissibility.py:classify_context()` |
| 2 | Provenance ledger | Persists every classified item and every override in append-only SQLite tables | `provenance/ledger.py`, `provenance/overrides.py`, `schema/provenance.sql` |
| 3 | Applied insight compiler | Transforms raw feedback/process material into derived requirements; raw text never reaches Layer 5 | `provenance/context_admissibility.py:derive_requirement()` |
| 4 | Context admissibility | Decides per-item what each actor (classifier, writer, reviewer, auditor) is permitted to see | `provenance/context_admissibility.py` |
| 5 | Clean-room writer pack | Composes the only context the writer ever sees: Clean Brief, Approved Sources, Style Rules, Acceptance Tests, Banned Residue List | `provenance/writer_pack.py:compile_writer_pack()` |
| 6 | Clean-room generation (discipline mode) | Refuses arbitrary context kwargs at the writer entry point; the writer runs against only the pack | `provenance/clean_room.py:prepare_invocation()` |
| 7 | Output integrity gates | G1 prose boundary, G2 claim provenance, G3 self-grounding (BUILT); G4 contamination, G5 calibration (NOT BUILT, stubs explicit) | `provenance/context_admissibility.py:scan_prose_boundary()`, `provenance/verify.py`, `provenance/gates.py` |
| 8 | Human review and decision authority | Structured override schema: empty `risk_accepted` or `compensating_control` SHALL block the override; separation of duties downgrades final-prose to draft when the reviewer is also the writer | `provenance/overrides.py` |
| F | Foundation | Reader-facing override footer (SPEC-L8-S005), MCP server wrapper, shadow-mode observer | `provenance/footer.py`, `provenance/mcp_server.py`, `tools/warrantos-shadow-observe.py` |

## The four governance properties

A conformant WarrantOS implementation must be able to answer four
questions about any final artefact it produced, using the persisted
ledger, the CBOM, and the override ledger TOGETHER (no single
artefact is sufficient):

1. **Right context to the right actor.** Which roles saw which
   `context_id`s, AND which actor identity held each role?
2. **Right transformation for the right purpose.** How did process
   material become a derived requirement, claim, or style rule?
3. **Right output with provenance.** What supports every claim that
   appears, and what was deliberately blocked from appearing?
4. **Right accountability with human oversight.** Which gate verdicts
   fired, which overrides occurred, who recorded them, and under what
   structured rationale?

If a final artefact cannot answer one of these four questions, the
implementation is not conformant.

## How the parts fit together (one command)

```bash
python cli/warrantos_cli.py check draft.md \
  --context context.json \
  --actor-identity actor.json \
  --profile final-prose \
  --ci --json
```

Pipeline:

1. **Read** the draft and the JSON context items.
2. **Classify** each context item (Layer 1; SPEC-L1-S005 review-role
   gating threads `source_agent` through).
3. **Persist** the classifications per-run under
   `.warrant/runs/<run_id>/context_items.json`.
4. **Scan** the draft for prose-boundary violations against the
   profile (Layer 7 G1).
5. **Detect** factual-claim sentences via the shared `CLAIM_TRIGGERS`
   surface and salience-score each.
6. **Verify** (optional, `--verify`): for each detected claim, run
   the offline heuristic grader or the LLM grader if
   `ANTHROPIC_API_KEY` is set.
7. **Assemble** the CBOM v0.2 with `actor_identity`,
   `classification_overrides`, `override_ledger_refs`.
8. **Consolidate** a four-state verdict: PASS, HOLD, BLOCK, or
   NOT_ASSESSABLE (final-prose without `actor_identity` cannot
   certify as PASS).
9. **Emit** per-run JSON artefacts on disk and a one-line summary on
   stdout. With `--ci`, exit 1 on HOLD/BLOCK/NOT_ASSESSABLE.

The same pipeline is exposed as MCP tools via
`provenance/mcp_server.py` so Claude Code or Claude Desktop sessions
can call it directly.

## What is built today

- All eight layers have at least minimum conformance code on `main`.
- 365+ tests across 14 test modules, all passing on Python 3.8-3.13.
- CBOM canonical schema name `warrantos-cbom/v1` is stable per
  INV-007.
- The A1 classification-laundering attack and the A4 override
  permission-slip attack identified in Wave A QA are structurally
  closed at the schema and runtime layers.

## What is explicitly NOT built

- **Layer 7 G4 (contamination).** Requires a documented prompt-
  injection threat model and a labelled pattern corpus. The
  `provenance.gates.check_contamination()` stub raises
  `NotImplementedError` so callers detect the gap.
- **Layer 7 G5 (calibration).** Requires the verifier surface to
  emit a numeric confidence per claim, which the offline heuristic
  cannot guarantee. The `check_calibration()` stub raises.
- **Layer 6 subprocess isolation.** Level 2 conformance work; v0.5
  ships discipline mode only (kwarg refusal at the API surface).
- **Offline heuristic `contradicted` verdict.** The heuristic
  verifier cannot emit `contradicted` by construction. The BLOCK-on-
  contradicted branch fires only when an LLM grader is configured.
- **SPEC-L1-S006 labelled classifier corpus.** A useful regression
  corpus requires authored examples per class (N >= 50). Not
  fabricated by the pipeline; awaits a human-authored corpus.

These limits are documented in CHANGELOG.md and surfaced through the
test suite (the deferred-gate stubs raise, the test verifies the
raise, the gap is visible).

## Where to start reading

For a fresh contributor:

- **README.md** — the original Provenance Loop pitch and the v0.4
  "What is new" section.
- **docs/STACK.md** — the five-surface implementation map (older
  v0.1 framing; still accurate at the implementation surface
  level).
- **docs/CONTEXT-ADMISSIBILITY.md** — the per-class admissibility
  rules.
- **docs/MULTI-AGENT-REVIEW.md** — the review-panel pattern.
- **CHANGELOG.md** — what landed in each version, with explicit
  scope-out lists.
- **cli/warrantos_cli.py** — the one entrypoint that pulls every
  layer together; reading this file is the fastest way to see how
  the layers connect.

## The honest pitch

`claude-provenance` does not guarantee AI-assisted writing is
correct. It guarantees three things instead:

1. Unsourced or unsupported claims are expensive instead of
   invisible.
2. Process material cannot reach final prose without a recorded
   transformation.
3. Overrides cannot reach the public artefact without a structured
   rationale and a reader-facing footer.

The remaining failure modes need writer-side discipline, human
review, and the four-paper coupling thesis that motivates the whole
exercise. The repository ships the operational form of that thesis,
nothing more, nothing less.
