# Deploying the browser verifier

This directory is deploy **prep**, not a deploy. Nothing here has been
published; `deploy/verifier/` is the exact static site root to publish, and
`deploy-verifier.ps1` is the script that publishes it when you choose to run
it.

## What is here

- `verifier/index.html`: an unmodified copy of [`web/verify.html`](../web/verify.html),
  the zero-backend, client-side `.warrant` verifier described in
  [`web/README.md`](../web/README.md) and [`docs/VERIFICATION.md`](../docs/VERIFICATION.md).
  Do not hand-edit this copy; edit `web/verify.html` and re-copy it.
- `verifier/_headers`: Cloudflare Pages response headers: a Content-Security-Policy
  that mirrors the page's own inline `<meta>` CSP (plus `base-uri`,
  `form-action` and `frame-ancestors`, which only take effect as an HTTP
  header), `X-Content-Type-Options: nosniff`, and `Cache-Control: no-cache`
  on `index.html` so a redeploy is never served stale.
- `deploy-verifier.ps1`: the one-command publish script (see below).
- `verifier-sha256.txt`: the SHA-256 digest of `verifier/index.html`,
  recomputed by the deploy script on every run.

## One-command deploy

```powershell
$env:CLOUDFLARE_ACCOUNT_ID = '<your-cloudflare-account-id>'
./deploy/deploy-verifier.ps1
```

The script:

1. **Drift guard.** Refuses to run if `verifier/index.html` no longer matches
   `web/verify.html` byte-for-byte. If you edited the page, re-copy
   `web/verify.html` to `verifier/index.html` first.
2. Recomputes the SHA-256 of `verifier/index.html` and overwrites
   `verifier-sha256.txt` with it, so the digest you publish always matches
   what is about to ship.
3. Runs `wrangler pages deploy deploy/verifier --project-name warrantos-verify`,
   the one network-mutating step.

### Requirements

- **Wrangler CLI**, authenticated: run `wrangler login` once if you have not.
- **`CLOUDFLARE_ACCOUNT_ID`** set in the environment. Per the workspace setup
  notes, Juan's Wrangler install needs this variable explicitly; it is not
  picked up from the Cloudflare dashboard automatically. Set it as a Windows
  user environment variable or export it for the session as shown above.
  Never put the account ID or any Cloudflare API token in this repo or in
  chat.
- A Cloudflare Pages project named `warrantos-verify` (the script creates
  it on first deploy if it does not already exist; Wrangler will prompt).

### Project name and custom domain

`warrantos-verify` is the suggested Pages project name used above and in
`deploy-verifier.ps1`. `verify.warrantos.dev` is a **suggested** custom
domain if the `warrantos.dev` domain is registered and pointed at
Cloudflare, not a live or claimed domain today. Wiring a custom domain is a
separate step in the Cloudflare Pages dashboard (Custom domains) or via
`wrangler pages domain add`, after the first deploy succeeds.

## Publish the hash

`docs/VERIFICATION.md` documents `web/verify.html` as the offline, no-install
way to check a `.warrant` bundle "with no access to the original ledger."
That only holds if the page itself is not tampered with in transit or on the
host. Once deployed, publish `verifier-sha256.txt`'s digest next to the
verifier's download or landing link (release notes, README, or wherever the
link to the hosted verifier is shared) so a reader can confirm the page they
loaded is the one that was reviewed, the same pattern the project already
uses for `.warrant` bundles themselves: do not ask for trust, give the
reader something to recompute.

```
verify.warrantos.dev  (sha256:<digest from deploy/verifier-sha256.txt>)
```

## What this is not

This is prep only. No `wrangler deploy` or `wrangler publish` has been run
as part of preparing this directory, and nothing here has touched the
network. Running `deploy-verifier.ps1` to completion is a deliberate,
separate decision for whoever has the Cloudflare credentials.
