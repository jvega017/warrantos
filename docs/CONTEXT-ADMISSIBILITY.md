# Context Admissibility

Context Admissibility extends the Provenance Loop beyond citations. It covers
the messy material that shapes AI-assisted work but should not automatically
appear in final prose: feedback, prior drafts, tool traces, style directions,
operator notes, and private reasoning.

The principle is simple:

> Context may influence an artefact only through an allowed transformation.
> Context may appear in final prose only when its class permits that use.

This protects the reader-facing artefact from process leakage such as "based
on your feedback", "this version is now stronger", or "as discussed". Those
phrases may be true about the workflow, but they are usually inadmissible in a
final brief, paper, or client-ready document.

## Admissibility Questions

Each context item is classified against four questions:

1. What kind of context is this?
2. May it influence the output?
3. May it appear in final prose?
4. If it can influence the output, what transformation is allowed?

The current implementation is rule-based and conservative. It is designed to
make decisions inspectable, not to infer every nuance.

## Current Context Types

The eleven canonical SPEC §2.2 context classes implemented in
`provenance/context_admissibility.py`:

| Context type | Ledger bucket | Can influence output | Can appear in final prose | Allowed transformation |
| --- | --- | --- | --- | --- |
| `empirical_evidence` | `empirical` | yes | yes | `claim_or_citation` |
| `instruction` | `process` | yes | no | `derived_requirement` |
| `style_signal` | `synthesised` | yes | no | `style_rule` |
| `user_feedback` | `synthesised` | yes | no | `derived_requirement` |
| `prior_artefact` | `process` | yes | no | `derived_requirement` |
| `process_history` | `process` | yes | no | `derived_requirement` |
| `operational_trace` | `process` | no | no | `audit_record` |
| `review_finding` | `synthesised` | yes | no | `applied_recommendation` |
| `validation_rule` | `process` | yes | no | `boundary_rule` |
| `synthesised_judgement` | `synthesised` | yes | no | `derived_requirement` |
| `private_reasoning` | `excluded` | no | no | `none` |

The table is a policy surface. SPEC-L1-S005 review-role gating threads
the `source_agent` keyword through `classify_context()` so a
`policy-red-team` review item stays a `review_finding` rather than
being demoted into `user_feedback`. Future versions may refine these
types; the eleven-class set is the v0.9 canonical surface.

## Allowed Transformations

`claim_or_citation` means the material can appear as a final claim only when
it is cited or otherwise bound to a source.

`derived_requirement` means the underlying instruction may be applied, but
the drafting process must not be narrated. For example, "not commercial
enough" may become "strengthen commercial positioning"; it should not become
"based on your feedback, this is more commercial".

`style_rule` means the style instruction should affect wording, structure,
and tone without being announced to the reader.

`audit_record` means the material can be retained for traceability but should
not shape or appear in final prose.

`applied_recommendation` means a review finding may be applied as a revision
instruction by a revision planner; the recommendation itself does not appear
in final prose.

`boundary_rule` means a validation rule informs the prose-boundary gate (for
example, by extending the banned-residue list) but the rule text never
appears in final prose.

`none` means the material is excluded from generation.

## Prose Boundary Gate

The Prose Boundary Gate scans reader-facing text for process-to-prose
leakage. In the current implementation, the gate flags patterns such as:

- "based on your feedback";
- "as discussed";
- "this version";
- "previous draft";
- "more commercial";
- "I have incorporated";
- "operator notes".

The gate is not a style checker. It is a boundary check: did process context
cross into final prose when it should have been transformed first?

Audit and methodology artefacts may intentionally discuss process context.
The current implementation allows explicit roles such as `audit`,
`methodology`, and `consultation_report` to pass the boundary scanner.

## CBOM

The Context Bill of Materials records how context was handled. The current
CBOM report includes:

- total context item counts;
- counts for influence, final-prose admissibility, audit-only, and excluded
  material;
- admissibility summaries for each context item;
- derived transformations;
- prose-boundary verdict and violations.

Example CLI use:

```text
python cli/provenance_cli.py --cbom --context context.json final.md
python cli/provenance_cli.py --cbom --context context.json --json final.md
python cli/provenance_cli.py --cbom --context context.txt --ci final.md
```

JSON context accepts a list of items:

```json
[
  {"id": "feedback_017", "text": "This is not commercial enough."},
  {"id": "source_001", "text": "Source: official report, 2026."}
]
```

Plain-text context is also accepted, one item per non-empty line.

## Limits

Context Admissibility does not prove that the final artefact is correct. It
does not replace human review. It does not detect every possible process leak.
It makes a specific class of leakage visible and gateable, and it gives
reviewers a compact record of how non-source context was transformed.
