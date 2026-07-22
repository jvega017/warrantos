# Quickstart

This guide is for the current WarrantOS 0.11.0b2 local release candidate. It
does not claim that the candidate is available from PyPI or under an immutable
public tag.

## Install the candidate from its source checkout

```bash
git clone https://github.com/jvega017/warrantos.git
cd warrantos
python -m pip install -e ".[attestation]"
warrantos --version
```

The core package is standard-library only. The `attestation` extra provides
Ed25519 signing and verification. Use `[mcp]` only when you need the optional
MCP server.

When 0.11.0b2 is actually published, the release documentation will replace
this source-install command with the exact tagged package command. Until then,
do not infer that the public 0.10.0 package contains candidate behaviour.

## Run the retained demonstration

```bash
warrantos demo --output warrantos-demo
```

The demonstration deliberately produces a `BLOCK` decision, then retains:

- the synthetic draft, context and actor records;
- the complete `.warrant/runs/<run_id>` check output;
- `demo.warrant`;
- an offline verification result over the exact draft bytes.

Re-run the printed verification command. For the explicitly unsigned synthetic
demo it has this shape:

```bash
warrantos verify-external warrantos-demo/demo.warrant \
  --prose warrantos-demo/draft.md --allow-unsigned
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

The repository ships a composite GitHub Action and pre-commit hooks. The local
0.11.0b2 candidate Action intentionally remains locked to the latest published
0.10.0 distribution until promotion. The public-release gate fails if the
Action lock and plugin surfaces are not bumped to the promoted version.

Use newline-delimited Action paths, including for names containing spaces:

```yaml
- uses: jvega017/warrantos@v0.10.0
  with:
    mode: both
    paths: |
      docs
      policy drafts
```

Do not use mutable `@main` for a governance gate. See
[Distribution surfaces](DISTRIBUTION.md) and [production deployment](PRODUCTION-DEPLOYMENT.md).

## Next references

- [Overview](OVERVIEW.md)
- [Status](STATUS.md)
- [Limitations](LIMITATIONS.md)
- [MCP configuration](MCP-CONFIG.md)
- [Cost controls](COST.md)
- [Security policy](../SECURITY.md)
- [Issue tracker](https://github.com/jvega017/warrantos/issues)
