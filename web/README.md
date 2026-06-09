# WarrantOS web verifier

A single static page that verifies a `.warrant` bundle entirely in the browser. Nothing is uploaded.

- **Integrity** (recompute the Merkle root from the ledger entries and match the checkpoint) and the **prose digest** verify with no dependencies.
- **Signature** uses the browser Web Crypto Ed25519 to confirm who vouched for the ledger state.

Host `verify.html` anywhere static (GitHub Pages, Cloudflare Pages) or open it locally. It reproduces the Python verifier byte-for-byte (RFC 6962 leaf/node domain separation, canonical JSON with ensure_ascii escaping, base64url keys), validated headless against a real signed bundle.
