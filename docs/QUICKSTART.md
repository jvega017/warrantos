# Quickstart

This guide is for the current WarrantOS 0.11.0b2 local release candidate. It
does not claim that the candidate is available from PyPI or under an immutable
public tag.

## Install the authenticated candidate bundle

The public 0.10.0 package, GitHub Action and pre-commit ref are affected by the
P0 artefact-binding advisory and are not recommended. A source checkout is a
development environment, not an authenticated adopter release.

The only recommended current adopter path is the **authenticated 0.11.0b2
candidate bundle** distributed with Vega Runtime. Obtain its installer and
manifest digests out of band, then authenticate the installer before execution:

```powershell
$expectedInstallerSha256 = "<out-of-band install.ps1 SHA-256>"
$expectedManifestSha256 = "<out-of-band artifact-manifest.json SHA-256>"
if ((Get-FileHash -LiteralPath .\install.ps1 -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedInstallerSha256) { throw "Untrusted installer bytes" }
.\install.ps1 -ExpectedManifestSha256 $expectedManifestSha256
.\.vega-venv\Scripts\warrantos --version
```

The parent-shell check authenticates `install.ps1`; the installer then verifies
the signed manifest and exact WarrantOS and Vega wheel digests. The current
supported bootstrap is PowerShell. macOS and Linux adopters should wait for the
tagged public promotion. Do not infer that public 0.10.0 contains candidate
behaviour.

## Run the retained demonstration

```powershell
.\.vega-venv\Scripts\warrantos demo --output .\warrantos-demo
```

The demonstration deliberately produces a `BLOCK` decision, then retains:

- the synthetic draft, context and actor records;
- the complete `.warrant/runs/<run_id>` check output;
- `demo.warrant`;
- an offline verification result over the exact draft bytes.

Re-run the printed verification command. For the explicitly unsigned synthetic
demo it has this shape:

```powershell
.\.vega-venv\Scripts\warrantos verify-external .\warrantos-demo\demo.warrant `
  --prose .\warrantos-demo\draft.md --allow-unsigned
```

`BLOCK` and `VALID` answer different questions. `BLOCK` means the draft is not
fit to ship under the declared prose/claim policy. `VALID` means the retained
attestation has not been substituted and binds the selected draft. Neither
state proves that the draft is factually true.

## Check your own document

Generate starter metadata:

```bash
warrantos init --dir warrantos-inputs
```

Then run:

```bash
warrantos check YOUR_DRAFT.md \
  --context warrantos-inputs/context.json \
  --actor-identity warrantos-inputs/actor.json \
  --profile final-prose
```

The command prints the exact run directory. Turn that run into a portable
attestation and verify it:

```bash
warrantos attest YOUR_DRAFT.md \
  --run-dir .warrant/runs/RUN_ID --out YOUR_DRAFT.warrant
warrantos verify-external YOUR_DRAFT.warrant --prose YOUR_DRAFT.md \
  --allow-unsigned
```

Remove `--allow-unsigned` for a signed release. Supply the expected public key
out of band with `--key` when signer attribution matters.

## Verdicts and truth boundary

| Verdict | Meaning |
|---|---|
| `PASS` | No configured gate found a release-blocking condition. |
| `HOLD` | A load-bearing claim is unsupported or cannot be assessed. |
| `BLOCK` | A configured hard gate failed, such as a prose-boundary violation or contradiction. |
| `NOT_ASSESSABLE` | Required assessment inputs, such as actor identity, are absent. |

WarrantOS does not detect truth. Standalone WarrantOS can establish exact-byte
integrity and the evidence-only `passage_reproduced` state, but authenticated semantic support must be
supplied by an embedding runtime such as Vega.

## CI and integration

Do not enable the public GitHub Action or pre-commit hook while their immutable
public ref resolves to 0.10.0. The repository keeps those surfaces version-locked
for reproducibility, but they are deliberately **not an acquisition
recommendation** during the P0 advisory. The public-release gate requires the
Action lock and plugin surfaces to move to 0.11.0b2 before promotion.

See [Distribution surfaces](DISTRIBUTION.md) for the blocked-state contract and
[production deployment](PRODUCTION-DEPLOYMENT.md) for the trust-root boundary.

## Next references

- [Overview](OVERVIEW.md)
- [Status](STATUS.md)
- [Limitations](LIMITATIONS.md)
- [MCP configuration](MCP-CONFIG.md)
- [Cost controls](COST.md)
- [Security policy](../SECURITY.md)
- [Issue tracker](https://github.com/jvega017/warrantos/issues)
