---
description: Summarise the provenance ledger for this workspace
---

Read the provenance ledger and produce a short integrity summary.

1. Locate the ledger. Use the `PROVENANCE_DB` environment variable if set,
   otherwise `./.provenance/provenance.db` relative to the current directory.
2. If it does not exist, say so and stop.
3. Query `provenance_run` and `provenance_claim` and report:
   - runs recorded, and the date range
   - total claims checked, and the supported / [CITE NEEDED] / unsupported split
   - the unsupported-claim rate as a percentage, rounded to one decimal
   - the 10 most recent unsupported claims, with their trigger type
4. Close with one line: is the unsupported rate trending up or down across
   the last 5 runs. State the numbers. Do not speculate beyond the data.

Australian English. No em dashes. No hype. Numbers before narrative.
