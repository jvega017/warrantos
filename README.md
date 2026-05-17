# claude-provenance

[![ci](https://github.com/jvega017/claude-provenance/actions/workflows/ci.yml/badge.svg)](https://github.com/jvega017/claude-provenance/actions/workflows/ci.yml)

**The Provenance Loop: every factual claim carries a source, or it gets caught.**

Coding agents are judged on whether the code runs. Serious written work is
judged on whether the claims are true. `claude-provenance` is a Claude Code
plugin that closes that gap. It reads what the model just wrote, finds the
sentences that assert a fact, and checks each one for a source or an explicit
`[CITE NEEDED]` tag. Unsupported claims are logged to a portable ledger and
surfaced. In `enforce` mode they are handed straight back to the model to fix
before the turn can end.

It is a small idea, applied strictly. That is the whole point.

## Why this exists

This plugin is the operational form of a working paper, *From Citation to
Epistemic Governance* (Prometheus Policy Lab, in preparation). The argument:
AI failures in high-stakes work are rarely model-capability failures. They are
epistemic failures. The model states something with confidence and no
traceable source, and a human ships it. The fix is not a bigger model. It is a
loop that refuses to let an unsourced factual claim pass silently.

## What it catches (v0, by design)

The detector is a heuristic, deliberately. It targets the claim types that do
the damage in policy and research writing:

- years and dates
- percentages and "per cent"
- magnitudes (million, billion, trillion)
- statute and section references
- attribution verbs ("according to", "found that", "estimated", "shows that")

A claim counts as **supported** when its own sentence carries a URL, a
`(Source: ...)` note, a markdown link, a footnote, or an APA-style
`(Author, Year)`, or when the sentence immediately after it is itself just a
source (for example a `Source: https://...` line directly below the claim). A
claim with an explicit `[CITE NEEDED]` is **tagged** and treated as honest,
not as a violation. Everything else is **unsupported**. A source two or more
sentences away does not rescue a claim: that bleed was the v0 false negative
and is closed by design.

This will produce false positives and false negatives. It is a tripwire, not
an oracle, and it does not replace human review. It is honest about that.

## Install

Local (development):

```
/plugin marketplace add /path/to/claude-provenance
/plugin install claude-provenance
```

Or copy the folder into your plugins directory and restart Claude Code.
Requires Python 3.8+ on `PATH`. No third-party packages.

## Configuration

| Variable          | Values                     | Default                       |
|-------------------|----------------------------|-------------------------------|
| `PROVENANCE_MODE` | `report`, `enforce`, `off` | `report`                      |
| `PROVENANCE_DB`   | path to SQLite file        | `./.provenance/provenance.db` |

- **report** logs every run and prints a summary. Non-blocking.
- **enforce** blocks the end of a turn (or a file write) when an unsupported
  factual claim is present, and returns the list to the model to source.
- **off** disables the hook.

The Stop hook is loop-safe: it never blocks the same turn twice.

## Inspect the ledger

```
/provenance-report
```

Or directly:

```
sqlite3 .provenance/provenance.db \
  "SELECT status, COUNT(*) FROM provenance_claim GROUP BY status;"
```

## Tests

Stdlib only, no test dependencies. From the repo root:

```
python -m unittest discover -s tests -v
```

The suite covers the heuristic (each trigger type, inline and adjacent
sourcing, the closed v0 false negative), the loop-safety guard, enforce-mode
blocking, and the rule that an internal error must never break the session.

## Roadmap

- v0: heuristic detector, ledger, report and enforce modes (this release)
- v1: optional LLM grader for claim extraction and source-match quality
- v2: auto-fetch a cited URL and check the claim is actually supported by it
- v3: one-command export to an evidence matrix for a paper or brief

## Licence

MIT. Built by Juan Vega, Prometheus Policy Lab.
