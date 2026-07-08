---
description: Run the WarrantOS claim gate over a draft and report the verdict
---

Run WarrantOS's `check` pipeline over a single draft file and report the result plainly.

1. Determine the target file.
   - If `$ARGUMENTS` names a file, use that path.
   - Otherwise, use the most recently written or edited Markdown/text file in this
     session (the last file touched by a Write or Edit tool call).
   - If neither is available, say so and stop.

2. Run the check with the `brief-light` profile:

       warrantos check <path-to-file> --profile brief-light --json

   Use the `python -m warrantos.cli.warrantos_cli check` form if the `warrantos`
   console script is not on PATH.

3. Report, in this order:
   - The verdict: `PASS`, `HOLD`, `BLOCK`, or `NOT_ASSESSABLE`.
   - Claims detected, claims supported, claims unsupported (counts from the JSON
     output).
   - Every offending sentence, quoted in full, with its salience score and the
     rule that fired (from the `reasons` array in the JSON output). Do not
     paraphrase the sentences.
   - The run's output directory (`out_dir` in the JSON output), so the full
     ledger can be inspected.

4. Close with one line stating whether the draft is ready to ship (`PASS`) or
   what must change before it is (`HOLD`, `BLOCK`, `NOT_ASSESSABLE`), naming the
   specific claim or residue that needs a source, a `[CITE NEEDED]` tag, or
   removal.

Australian English. No em dashes. No hype. Numbers before narrative.
