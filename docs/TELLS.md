# warrantos tells

`warrantos tells` is the opinionated sibling of `warrantos slop`.

`slop` hunts for chat *residue*: scaffold that visibly leaked out of an
assistant session and shipped by accident: assistant openers, identity
disclaimers, stray TODO placeholders. Those patterns are close to objective. A
sentence that opens with "Certainly, the analysis below" is almost never
something a person typed on purpose into a policy brief.

`tells` hunts for something harder to pin down: prose that is already clean
of residue but still *sounds* machine-written. Contrastive negation, hedge
stacking, em-dash punctuation, a small set of filler phrases, and a drumbeat
of formulaic paragraph-openers. None of these are proof that a model wrote
the sentence. Humans write every one of them, some of them often. `tells`
flags them anyway because they are disproportionately common in unedited
model output, and a reviewer who sees ten of them in one document has a
reason to slow down and read closely.

## Usage

```
warrantos tells docs/ README.md         # scan paths for AI-writing tells
warrantos tells --json docs/            # machine-readable output
warrantos tells --badge docs/           # emit a badge URL
warrantos tells --fail-over 0 docs/     # CI mode: non-zero exit above the threshold
warrantos tells --include-fences docs/  # also scan inside fenced code blocks
```

Same flags and semantics as `warrantos slop`: `[PATH...]` (files or
directories, default the current directory), `--json`, `--badge`,
`--fail-over THRESHOLD`, `--include-fences`. Fenced code blocks are skipped
by default because they usually quote deliberate examples, including the
example strings in this document. A TELL SCORE runs 0.0 to 10.0 on the same
density formula as SLOP SCORE, and the exit contract is identical: 0 unless
`--fail-over` is exceeded (1) or a path does not exist (2).

`tells` reuses the slop scanning engine rather than reimplementing it: file
discovery, fence handling, display-path resolution, the score formula, and
the badge base all come from `warrantos.provenance.slop`. Only the rule set
is new.

## Why this scanner is opinionated where slop is objective

`slop`'s pattern list is the canonical `_AI_RESIDUE_RULES` set shared with
the Layer 7 G1 prose-boundary gate: a `slop` finding and a `check`
violation are always the same rule, and there is little room for house
taste in an assistant self-identification phrase showing up in a shipped document.

`tells` has no such external anchor. Every rule below is a house-style
call. Some newsrooms use em dashes freely. Some technical writers stack
hedges on purpose to be precise about uncertainty. A team that dislikes
"Furthermore" as a paragraph opener will set a lower `--fail-over`
threshold than a team that does not care. `tells` does not claim these
choices are universal; it applies one particular set of them, consistently,
so a reviewer gets a repeatable signal instead of a vibe.

## Rule families

Each finding reports its file, line, matched text, category, and rule id.

### 1. contrastive-negation

The "not X, but Y" / "it's not X, it's Y" family, with the pivot required
within roughly 60 characters of the trigger phrase so an unrelated long
sentence that happens to contain both halves does not fire.

Real example (fenced so the scanner treats it as quoted, not live prose):

```
This is not just a policy, it is a whole new operating model, but the
paper does not say how.
```

Deliberately not flagged: bare "rather than" and "instead of" are far too
common in ordinary prose to be a useful signal on their own, and the near
miss below stays silent because there is no "but" pivot within range: it
is just a sentence with two clauses, not the contrastive-negation shape.

```
Not only did the committee meet, it voted on the motion immediately.
```

### 2. hedge-stacking

Two or more hedges from one fixed word list, inside one sentence
(sentences are split on period, exclamation mark, question mark):

```
may, might, could, perhaps, possibly, arguably, potentially, seemingly,
somewhat, appears to, tends to
```

Real example:

```
The measure might possibly reduce costs, though implementation could
arguably take longer than planned.
```

One hedge in a sentence is ordinary, defensible caution about an uncertain
claim and does not fire:

```
The measure could reduce costs over the medium term.
```

The stack, not the hedge, is the tell.

### 3. dash-punctuation

An em dash used as punctuation anywhere in a line, or a spaced en dash
(with whitespace on both sides). Number ranges written without spaces are
left alone: the spacing is what marks the dash as punctuation rather than
a range separator.

```
The scheme failed - not because of design, but delivery.       (em dash fires)
The review ran 2020 - 2021 across three agencies.               (spaced en dash fires)
The review ran 2020-2021 across three agencies.                 (no spaces, does not fire)
```

This project's own documentation treats "no em dashes" as house law (see
the workspace writing rules); here it is one opinion among five, weighted
the same as the others, because a general-purpose scanner cannot assume
every user shares that preference.

### 4. filler-lexicon

A short list of near-unambiguous AI filler phrases, case-insensitive:

```
delve into
rich tapestry
stands as a testament
in today's fast-paced
in today's rapidly evolving
it is important to note that
it's worth noting that
in the ever-evolving
game-changer
unlock the (full) power / potential
seamlessly integrates
at the end of the day,
let's dive in
```

Real example:

```
Let us delve into the detail of the funding model.
```

### 5. formulaic-transition

Sentence-initial "In conclusion,", "Furthermore,", "Moreover,",
"Additionally," -- only when two or more of them (in any combination)
appear in the same document. A single one opening a paragraph is normal,
human paragraph construction and is not reported. The second and any
later occurrence in the same document are reported: the drumbeat
is the tell, not the individual word.

## Honest limits

`tells` measures style markers, not authorship. Every pattern above has a
plausible human origin: careful hedging, a fondness for em dashes, a
writer who leans on "Furthermore" out of habit. A high TELL SCORE is a
prompt to open the document and read the flagged lines, never proof that a
model wrote them, and a low score is not proof that a human did. Sentence
splitting is a simple `.`/`!`/`?` scan with no abbreviation handling, so an
abbreviation like "e.g." can occasionally split a sentence early; this
mainly affects hedge-stacking and formulaic-transition counts and is a
known, accepted trade-off for staying stdlib-only and fast. Rules are
tuned for precision over recall throughout: a false positive on legitimate
prose is treated as worse than a miss, so `tells` will under-report before
it will nag.
