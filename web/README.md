# WarrantOS web verifier

A single static page that verifies a `.warrant` bundle entirely in the browser. Nothing is uploaded.

- **Integrity** (recompute the Merkle root from the ledger entries and match the checkpoint) and the **prose digest** verify with no dependencies.
- **Signature** uses the browser Web Crypto Ed25519 to confirm who vouched for the ledger state.

Host `verify.html` anywhere static (GitHub Pages, Cloudflare Pages) or open it locally. It reproduces the Python verifier byte-for-byte (RFC 6962 leaf/node domain separation, canonical JSON with ensure_ascii escaping, base64url keys), validated headless against a real signed bundle.

The file picker is a native keyboard-operable button, parse failures and
verification results are announced through a focus-managed live status region,
and visible keyboard focus is preserved. Static accessibility contract tests
run in the suite. This is not a claim of WCAG conformance: current Chrome,
Edge, Firefox, zoom, NVDA, and VoiceOver acceptance still requires witnessed
browser and assistive-technology testing.
