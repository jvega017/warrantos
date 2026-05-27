# claude-provenance

[![ci](https://github.com/jvega017/claude-provenance/actions/workflows/ci.yml/badge.svg)](https://github.com/jvega017/claude-provenance/actions/workflows/ci.yml)
![status: beta](https://img.shields.io/badge/status-beta-orange)
![python: 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![deps: stdlib only](https://img.shields.io/badge/deps-stdlib%20only-green)

**The Provenance Loop: every factual claim carries a source, that source is checked, or it gets caught.**

Coding agents are judged on whether the code runs. Serious written work is
judged on whether the claims are true. `claude-provenance` is the reference
implementation of WarrantOS: a governance harness for AI-assisted writing
that ships clean prose and a separate auditable provenance ledger.

It is a small idea, applied strictly. That is the whole point.

## Quickstart

```bash
pip install claude-provenance

# Run the bundled demo: writes per-run artefacts under .warrant/runs/
warrantos check examples/quickstart-demo/draft.md \
  --context examples/quickstart-demo/context.json \
  --actor-identity examples/quickstart-demo/actor.json \
  --profile final-prose
```

Five-minute tour: [`docs/QUICKSTART.md`](docs/QUICKSTART.md).
Connect to Claude Code / Claude Desktop: [`docs/MCP-CONFIG.md`](docs/MCP-CONFIG.md).
Cost model and spend control: [`docs/COST.md`](docs/COST.md).
Whole-repository tour: [`docs/OVERVIEW.md`](docs/OVERVIEW.md).

## WarrantOS framing

`claude-provenance` is now framed as an early WarrantOS implementation: a
warrant layer for AI-assisted work that makes claims, sources, context use and
release gates inspectable. The current repo does not implement a complete
compliance platform. It implements useful pieces of the stack:

- the Provenance Ledger for claim detection, verification outcomes and
  epistemic-debt tracking;
- Context Admissibility for deciding which process context may influence final
  prose;
- CBOM export for a compact Context Bill of Materials;
- a Prose Boundary Gate for blocking process narration in reader-facing text;
- BriefLock and Multi-Agent Review as product and workflow frames over the
  existing hook, CLI, ledger and review surfaces.

Start with [`docs/STACK.md`](docs/STACK.md) for the product map,
[`docs/CONTEXT-ADMISSIBILITY.md`](docs/CONTEXT-ADMISSIBILITY.md) for CBOM and
prose-boundary rules, and
[`docs/MULTI-AGENT-REVIEW.md`](docs/MULTI-AGENT-REVIEW.md) for the review
workflow.

## What is new (Path X3 + X4)

The integration CLI `cli/warrantos_cli.py` now wires the WarrantOS upstream
leg end-to-end: Layer 1 classification with SPEC-L1-S005 review-role gating,
Layer 7 G1 prose-boundary scan, Layer 7 G2 claim detection, CBOM v0.2
assembly with `actor_identity` and override-ledger references, and a
four-state consolidated verdict (PASS, HOLD, BLOCK, NOT_ASSESSABLE):

```
python cli/warrantos_cli.py check draft.md \
  --context context.json \
  --actor-identity actor.json \
  --profile final-prose \
  --ci --json
```

The structured human-override ledger (`provenance.overrides`) enforces
SPEC-L8-S004 at the write path: empty `risk_accepted` or
`compensating_control` SHALL block the override, so the row does not
exist if it cannot be recorded. SPEC-L8-S003 separation-of-duties:
when the reviewer identity matches the writer-pack actor identity for a
final-prose artefact, the role is downgraded to `draft`.

The MCP server (`provenance/mcp_server.py`) wraps the pipeline as four
tools (`warrant_check`, `warrant_classify`, `warrant_record_override`,
`warrant_get_run`) callable from Claude Code or Claude Desktop. The
`mcp` SDK is an optional dependency; `call_tool_in_process()` works
without it as a plain Python API.

The shadow observer (`tools/warrantos-shadow-observe.py`) runs the
pipeline over an already-published artefact in observation mode only.
Never blocks. Never modifies production scripts. Appends a single
JSON-line summary per run to a shadow log with a "NOT enforced" marker
on every row.

See [`CHANGELOG.md`](CHANGELOG.md) for the full Path X3 + X4 entry,
and [`docs/STATUS.md`](docs/STATUS.md) for the live per-layer
conformance dashboard (run `warrantos status` locally to refresh).

If you just landed on the repo and want the tour, start with
[`docs/OVERVIEW.md`](docs/OVERVIEW.md). It walks through what is in
the repository, in order, with explicit "what is built today" and
"what is NOT built" lists.

## Why this exists

This plugin is the operational form of a working paper, *From Citation to
Epistemic Governance* (Prometheus Policy Lab, in preparation). The argument:
AI failures in high-stakes work are rarely model-capability failures. They are
epistemic failures. The model states something with confidence and no
traceable source, a human under time pressure ships it, and the error was
never about model size. The fix is a loop that refuses to let an unsourced or
unverified claim pass silently.

## Two axes: detection and verification

`claude-provenance` separates two questions that most tools conflate.

**Axis 1, detection (in-session, stdlib only, zero network).** The hook reads
what the model wrote and classifies each factual sentence as **supported** (a
source is present in its own sentence or the line directly below it),
**tagged** (an explicit `[CITE NEEDED]`, treated as honest), or
**unsupported** (nothing). A source two or more sentences away does not rescue
a claim: that bleed was the v0 false negative and is closed by design. This
axis stays a fast tripwire that never does network I/O and never breaks the
session.

**Axis 2, verification (out of band).** The verifier takes a detected claim,
fetches the cited URL, and assigns one of: **verified**, **contradicted**,
**not_addressed**, **unverifiable** (a citation exists but cannot be
machine-checked, for example an `(Author, Year)` with no URL), **skipped**, or
**error**. By default this uses an offline token-overlap heuristic. If
`ANTHROPIC_API_KEY` is set it uses an LLM grader, and on any failure it falls
back to the heuristic. The verifier is never called from the blocking hook.

The detector catches the cheap, common failure. The verifier targets the
expensive one: a claim that is confidently cited and wrong.

## The Provenance Loop

The pattern is platform-independent: Extract, Bind, Verify, Adjudicate,
Ledger. The Claude Code plugin is one instantiation. The full definition,
scope, and limits are in [`docs/PROVENANCE-LOOP.md`](docs/PROVENANCE-LOOP.md).

## Install

Local (development):

```
/plugin marketplace add /path/to/claude-provenance
/plugin install claude-provenance
```

Or copy the folder into your plugins directory and restart Claude Code.
Requires Python 3.8+ on `PATH`. No third-party packages.

## Configuration

| Variable                  | Values                     | Default                       |
|---------------------------|----------------------------|-------------------------------|
| `PROVENANCE_MODE`         | `report`, `enforce`, `off` | `report`                      |
| `PROVENANCE_DB`           | path to SQLite file        | `./.provenance/provenance.db` |
| `ANTHROPIC_API_KEY`       | API key                    | unset (verifier stays offline)|
| `PROVENANCE_GRADER_MODEL` | model id                   | `claude-haiku-4-5-20251001`   |

- **report** logs every run and prints a summary. Non-blocking.
- **enforce** blocks the end of a turn or a file write when an unsupported
  factual claim is present, and returns the list to the model to source.
- **off** disables the hook.

The Stop hook is loop-safe: it never blocks the same turn twice. With no API
key the verifier degrades to the offline heuristic with no error.

## Verify a draft from the command line

The CLI runs the loop over a file, a directory, or stdin, outside a live
session. Offline by default; `--verify` enables network fetch.

```
python cli/provenance_cli.py path/to/draft.md            # offline detection
python cli/provenance_cli.py --verify path/to/draft.md    # fetch and grade
python cli/provenance_cli.py --ci docs/                   # exit 1 on a miss
git diff --name-only | ... | python cli/provenance_cli.py --ci -
```

`--ci` exits 1 if any claim is `contradicted` or `unsupported`, so it drops
into a CI pipeline or pre-commit hook. `--json` emits machine-readable output.

In a session, `/provenance-report` summarises the ledger and
`/provenance-verify` runs the verification stage and returns recommendations.

## Build a Context Bill of Materials

CBOM mode checks a different boundary from claim provenance. It classifies
context material, records allowed transformations, and scans final prose for
process leakage.

```
python cli/provenance_cli.py --cbom --context context.json final.md
python cli/provenance_cli.py --cbom --context context.json --json final.md
python cli/provenance_cli.py --cbom --context context.txt --ci final.md
```

`--context` accepts JSON items such as
`{"id": "feedback_017", "text": "This is not commercial enough."}` or plain
text with one context item per non-empty line. In `--ci` mode, process leakage
such as "based on your feedback" causes a failing exit code.

## Governance: epistemic debt

The ledger is the point, not a side effect. `provenance/ledger.py` computes an
**epistemic-debt** metric (load-bearing unsupported claims, normalised, with a
direction over the last runs) and exports an evidence matrix to Markdown or
CSV. Load-bearing is scored by `provenance/salience.py`: a statutory reference
inside a recommendation is weighted above a date in passing. The governance
question is not "is this sentence cited" but "is our AI-assisted output getting
more or less sourced over time", and the ledger answers it.

## Evaluation

`eval/run_eval.py` runs the detector against the seed corpus and prints
precision, recall and F1 at run time. From v0.3 the harness also runs a
grader-precision-recall evaluation against a 60-item labelled corpus
(`eval/corpus/grader.jsonl`) and reports per-class metrics, a five-by-six
confusion matrix and a governance-framed caveat block. An evaluation-only
cross-model backend (`python eval/run_eval.py --grader codex`) drives a
local Codex CLI for a same-task different-model probe; it is never
auto-selected and never run in CI. The numbers are corpus-dependent and
not a claim of general accuracy: see [`eval/README.md`](eval/README.md),
which states the limits, the analytic nature of the contradicted-class
zero for the offline heuristic and the relevant prior art (McCoy, Pavlick
and Linzen 2019; Gao et al. 2023) plainly. The corpora are regression and
illustration seeds, not validated benchmarks.

## Tests

Stdlib only, no test dependencies. From the repo root:

```
python -m unittest discover -s tests -v
```

247 tests cover detection (every trigger, inline and adjacent sourcing, the
closed v0 false negative), the loop-safety guard, enforce-mode blocking, the
verifier (mocked network, LLM-failure fallback, no-key path), the CLI, the
ledger and salience scoring, the grader-eval path (`sys.modules`-isolated
under a unique spec name) and the Codex grader graceful-failure path. The
rule that an internal error must never break the session is enforced
throughout.

## Roadmap

- v0: heuristic detector, ledger, report and enforce modes. Done.
- v0.2: out-of-band verifier with fetch and graceful LLM grading, two-axis
  model, standalone CLI and CI mode, epistemic-debt metric and
  evidence-matrix export, salience weighting, evaluation harness.
- v0.3 (this release): grader precision/recall evaluation with a labelled
  60-item corpus and per-class P/R/F1; evaluation-only cross-model grader
  backend (`--grader codex`) for same-task different-model comparison;
  governance reframe of the eval documentation, positioning the contribution
  against HANS and ALCE rather than as a rediscovery of negation-blindness.
- v1: stronger claim extraction and source-match quality from the LLM grader.
- v2: deeper entailment, including PDF and paywalled-source handling.
- v3: one-command evidence-matrix export wired into a paper or brief workflow.

## Limits, stated plainly

The detector is a heuristic and will produce false positives and false
negatives. Offline verification only checks token overlap, not meaning. A
correctly sourced claim can still be misleading or selectively cited. This
tool makes an unsourced or unchecked claim expensive instead of invisible. It
does not replace human review and does not claim to.

## Licence

MIT. Built by Juan Vega, Prometheus Policy Lab.
