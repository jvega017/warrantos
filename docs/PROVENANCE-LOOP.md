# The Provenance Loop

## Definition

The Provenance Loop is a five-stage pattern for maintaining epistemic
integrity in any system that generates or processes written claims. The
pattern is platform-independent: it applies to document editors, AI coding
assistants, research pipelines, and automated report generators. The
`claude-provenance` plugin is one instantiation of the loop inside Claude Code.

The five stages are:

**Extract.** Identify sentences that assert a checkable fact. A checkable
fact is any sentence that contains a year, a proportion, a magnitude, a
statute reference, or an attribution verb ("according to", "found that",
"estimated", "shows that"). The extraction step makes no judgement about
truth: it finds candidates only. Any implementation of this stage will
produce false positives (claim-like sentences that are not really claims)
and false negatives (genuine claims the trigger rules miss). That is
acceptable. The loop treats extraction as a tripwire, not an oracle.

**Bind.** Attach the nearest claimed source to each extracted sentence.
A source may be an inline URL, a markdown hyperlink, a footnote reference,
an APA-style parenthetical, or a source-line immediately following the
claim. Binding is local: a source two or more sentences away does not
rescue an earlier claim. This rule is strict by design. The v0 false
negative that allowed distant sources to bleed onto unrelated claims is
closed. A sentence marked `[CITE NEEDED]` is treated as honestly
acknowledged and classified separately from unsupported claims.

**Verify.** For each bound claim-source pair, assess whether the source
actually supports the claim. The verification stage has two modes:

- Heuristic (offline). Presence of a well-formed source string counts as
  support. This mode is fast, deterministic, and requires no network
  access. It is the default mode for hooks that fire on every turn.
- Graded (online). The source is fetched, and the claim is tested for
  entailment against the retrieved content. A grader (human or LLM)
  assigns one of six verdicts: verified, contradicted, not_addressed,
  unverifiable, skipped, or error. This mode is accurate but slow and
  should be run on demand, not on every turn.

**Adjudicate.** Apply the policy gate. Three gate settings are available:

- `off`. No action taken. The loop runs silently.
- `report`. Log the results to the ledger and surface a summary. The
  turn is not blocked.
- `enforce`. Log the results. If any unsupported claim is present, block
  the turn and return the list of unsupported claims to the author so
  they can add sources before proceeding.

The gate setting is a policy choice. It is not a technical constraint.
An organisation that writes policy briefs may choose `enforce`. A research
notebook in early drafting may choose `report`. A completed publication
pipeline may choose `report` with a CI check that fails on any
`contradicted` verdict.

**Ledger.** Write a durable record of every run. The ledger captures the
timestamp, the session identifier, the source event, the file path, the
mode, and the full set of claims with their statuses. The ledger enables
trend analysis: is the unsupported-claim rate rising or falling over time?
It also enables audit: a reader of the final document can inspect the
ledger to see which claims were checked, when, and with what result. This
is epistemic debt tracking made operational.

## Scope and limits

The loop is designed for written prose that makes factual assertions. It
is not designed for code, mathematical notation, or creative fiction.

The heuristic extraction stage is deliberately narrow. It targets the
claim types that do the most damage in policy and research writing: numbers,
dates, magnitudes, statute references, and attribution verbs. A sentence
that asserts a fact without using any of these constructs will pass through
undetected. That is a known limit, not a bug. The loop catches common
failure modes; it does not guarantee completeness.

The verification stage depends on the quality of cited sources. A claim
supported by a broken URL, a paywalled article, or a source that does not
actually address the claim will pass the heuristic stage but fail graded
verification. Graded verification is the correct tool for high-stakes
documents.

The loop does not assess the quality of the claim itself. A claim may be
correctly sourced and still be misleading, out of context, or selectively
cited. Human review at the adjudication stage is always required for
consequential outputs.

## The claude-provenance instantiation

The `claude-provenance` Claude Code plugin implements the loop as follows:

- Extract and Bind are performed by `hooks/provenance_check.py` using the
  `analyse()` function. The function runs on every `Stop` event and on
  every `PostToolUse` event where the tool writes content (Write, Edit,
  MultiEdit).
- Verify (heuristic) is integrated into `analyse()`. Verify (graded) is
  available via `provenance.verify.verify_text()` and the `--verify` flag
  on the CLI.
- Adjudicate is controlled by the `PROVENANCE_MODE` environment variable
  (`report`, `enforce`, or `off`).
- Ledger is a portable SQLite database at `.provenance/provenance.db` (or
  the path set in `PROVENANCE_DB`).

The CLI (`cli/provenance_cli.py`) provides a standalone interface for
running the loop over files, directories, or stdin, outside of a live
Claude Code session. It is suitable for use in CI pipelines and pre-commit
hooks.

## Applying the loop to other systems

Any system that emits written claims can implement the Provenance Loop:

- A document management system can run the Extract and Bind stages at
  save time and flag unsupported claims in the UI.
- A continuous integration pipeline can run the full loop (including
  Verify-graded) on every pull request that touches documentation.
- A research assistant can run the loop as a post-processing step after
  generating a report, before delivering it to the user.
- A regulatory compliance tool can maintain a persistent ledger across
  document versions and report on epistemic-debt trends over time.

The key invariant across all instantiations: the loop must never silently
pass an unsupported factual claim. Silence is the failure mode. The loop
exists to make silence impossible.
