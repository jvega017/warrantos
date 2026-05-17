---
description: Run the full verification stage over the provenance ledger and the current draft
---

Run the verification stage of the Provenance Loop over the active ledger and
any draft files in the current workspace. Produce a short integrity summary
followed by three concrete recommendations.

Steps:

1. Locate the ledger. Use the `PROVENANCE_DB` environment variable if set,
   otherwise `./.provenance/provenance.db` relative to the current directory.
   If it does not exist, say so and stop.

2. Run the CLI verification pass over the most recent draft file in the
   workspace (prefer `.md` and `.txt` files modified in the last 24 hours).
   Use the command:

       python cli/provenance_cli.py --verify --json <path-to-draft>

   If no draft file is found, run the pass on the ledger's most recent
   `provenance_claim` entries by querying SQLite directly.

3. Produce a short integrity summary. Numbers before narrative. Include:
   - total claims verified this run
   - count and percentage for each verdict category
     (verified, contradicted, not_addressed, unverifiable, skipped, error)
   - count of unsupported claims from the heuristic pass
   - any `contradicted` claims listed in full with their claim text and
     the rationale provided by the grader

4. State whether the overall epistemic status is: clean, caution, or alert.
   - clean: zero contradicted, unsupported rate below 10 per cent
   - caution: zero contradicted but unsupported rate 10 per cent or above
   - alert: one or more contradicted claims present

5. Close with exactly three concrete recommendations. Each recommendation must
   name the specific claim or source that needs attention, state the action
   required (add source, remove claim, correct figure, verify URL), and
   identify where in the document the change should be made.

Australian English. No em dashes. Numbers before narrative. No hype.
