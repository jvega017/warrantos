# Conformance probe fixtures

Inputs for the per-layer execution probes
(`warrantos/provenance/conformance.py`). Each file is one adversarial
(or deliberately clean) fixture:

| File | Probe(s) | Expected enforcement |
|---|---|---|
| `private_reasoning.txt` | L1, L4, L5 | classified `private_reasoning`, excluded from prose, hidden from the clean-room writer |
| `feedback.txt` | L3 | a derived requirement is compiled and persisted to the ledger |
| `residue.md` | G1 | prose boundary blocks process-to-prose leakage |
| `claims.md` | G2 | claim triggers fire (year / percentage / attribution / named body) |
| `contamination.md` | G4 | prompt-injection pattern matches |
| `clean.md` | (sanity) | no G1 violations, no G4 matches |
| `ledger_entries.json` | I1, I3, I4 | Merkle root / warrant bundle tamper evidence |

The probes embed identical defaults so `warrantos.provenance.status.probe_results()`
works on an installed package without this directory; the test suite
(`tests/test_conformance.py`) loads these files and asserts both paths
agree.
