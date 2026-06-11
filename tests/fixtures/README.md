# Test fixtures for web/verify.html

## Fixture files

### xss_bundle.warrant

A .warrant file whose `root_hash` field contains an HTML img/onerror XSS payload.
Used to confirm that the page renders the value as inert literal text rather than
executing any script.

### badsig_bundle.warrant

A .warrant file with a structurally valid checkpoint but a deliberately corrupted
signature (all-zero bytes that cannot verify against any real key). Used to confirm
the SIGNATURE_INVALID tri-state path.

---

## Manual browser acceptance checklist (P0-1)

Open `web/verify.html` locally (file://) or from a local HTTP server.

### (a) XSS check

1. Drop `xss_bundle.warrant` onto the verifier.
2. Confirm `document.title` in the browser console remains "WarrantOS .warrant verifier".
3. Confirm the root hash value is displayed as the literal text
   `<img src=x onerror=document.title='pwned'>` inside the result card, not
   as a rendered image or script execution.
4. Expected verdict: NOT VALID (integrity will be INVALID because the root hash
   is not a real Merkle root).

### (b) Corrupted-signature check

1. Drop `badsig_bundle.warrant` onto the verifier.
2. Confirm the signature row shows `SIGNATURE_INVALID`.
3. Tick the "Accept unsigned bundles (absent signature only)" checkbox.
4. Confirm the overall verdict is still NOT VALID (SIGNATURE_INVALID must not be
   downgraded by the allow-unsigned toggle).

### (c) CSP and zero external requests check

1. Open browser DevTools, go to the Network tab.
2. Load `web/verify.html`.
3. Confirm the CSP meta tag is present in the page source:
   `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:;`
4. Drop either fixture file onto the verifier.
5. Confirm the Network tab shows zero requests to external origins during the
   entire verification process.
