# WarrantOS release truth

The machine-readable source for the current development checkout is
`release-manifest.json`.

As inspected on 2026-07-22, this working tree declares package version 0.11.0b1 but has no
`v0.11.0b1` Git tag and keeps the 0.11.0 security work in the Unreleased
changelog section. It is candidate `warrantos-0.11.0b1-local-rc.1` and must be
described as a local release candidate,
not as a completed tagged release. The latest tag in this checkout is v0.10.0.

The v2 warrant checkpoint binds the prose digest, CBOM digest and ledger root.
That implementation closes the earlier bundle-substitution defect. It does not
prove that a citation entails a claim, authenticate user-supplied actor labels,
create an external transparency timestamp or production-qualify the complete
system.

Use four separate maturity statements:

- Implemented: code or schema exists.
- Enforced: an execution probe observes the declared control.
- Evaluated: performance has been measured on a declared corpus.
- Production qualified: independent operational evidence supports reliance.

Do not use `BUILT` as a synonym for all four.

Claim support uses the following progression and adverse-outcome vocabulary. The first five states represent increasing evidence; the final two record challenge or contradiction:

1. `citation_present`
2. `source_resolved`
3. `passage_located`
4. `support_asserted`
5. `passage_reproduced` (exact evidence bytes/ranges reproduced; no semantic verdict)
6. `support_verified`
7. `support_contested`
8. `contradicted`

The current CLI adapter may detect a citation while leaving `support_ids`
empty. Such a record is `citation_present`, not semantically verified support.
The standalone evidence verifier can advance a binding only to
`passage_reproduced`. Its legacy reviewer/verdict inputs are unauthenticated
compatibility data and are ignored.
