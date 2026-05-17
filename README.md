# claude-provenance

[![ci](https://github.com/jvega017/claude-provenance/actions/workflows/ci.yml/badge.svg)](https://github.com/jvega017/claude-provenance/actions/workflows/ci.yml)

**The Provenance Loop: every factual claim carries a source, that source is checked, or it gets caught.**

Coding agents are judged on whether the code runs. Serious written work is
judged on whether the claims are true. `claude-provenance` is a Claude Code
plugin that closes that gap. A fast in-session tripwire catches sentences that
assert a fact with no source. An out-of-band verifier then fetches the cited
source and judges whether it actually supports the claim. Results go to a
portable ledger. In `enforce` mode an unsupported claim is handed back to the
model before the turn can end.

It is a small idea, applied strictly. That is the whole point.

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

## Governance: epistemic debt

The ledger is the point, not a side effect. `provenance/ledger.py` computes an
**epistemic-debt** metric (load-bearing unsupported claims, normalised, with a
direction over the last runs) and exports an evidence matrix to Markdown or
CSV. Load-bearing is scored by `provenance/salience.py`: a statutory reference
inside a recommendation is weighted above a date in passing. The governance
question is not "is this sentence cited" but "is our AI-assisted output getting
more or less sourced over time", and the ledger answers it.

## Evaluation

`eval/run_eval.py` runs the detector against a small hand-labelled corpus and
prints precision, recall, and F1 computed at run time. The numbers are
corpus-dependent and are not a claim of general accuracy: see
[`eval/README.md`](eval/README.md), which states the limits plainly. The
corpus is a regression and illustration seed, not a validated benchmark.

## Tests

Stdlib only, no test dependencies. From the repo root:

```
python -m unittest discover -s tests -v
```

170 tests cover detection (every trigger, inline and adjacent sourcing, the
closed v0 false negative), the loop-safety guard, enforce-mode blocking, the
verifier (mocked network, LLM-failure fallback, no-key path), the CLI, the
ledger and salience scoring, and the rule that an internal error must never
break the session.

## Roadmap

- v0: heuristic detector, ledger, report and enforce modes. Done.
- v0.2 (this release): out-of-band verifier with fetch and graceful LLM
  grading, two-axis model, standalone CLI and CI mode, epistemic-debt metric
  and evidence-matrix export, salience weighting, evaluation harness.
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
