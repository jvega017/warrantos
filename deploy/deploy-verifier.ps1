<#
.SYNOPSIS
  Deploy the WarrantOS browser verifier (deploy/verifier) to Cloudflare Pages.

.DESCRIPTION
  This script does three things, in order:
    1. Drift guard: refuses to run if deploy/verifier/index.html no longer
       matches web/verify.html byte-for-byte. The deploy copy must be a
       plain copy of the source page, never a hand-edited fork of it.
    2. Recomputes the SHA-256 of deploy/verifier/index.html and writes it
       to deploy/verifier-sha256.txt (overwriting the value committed at
       prep time), so the published digest always matches what is about
       to ship.
    3. Runs `wrangler pages deploy deploy/verifier --project-name
       warrantos-verify`, which is the one network-mutating step here.

  Wrangler needs CLOUDFLARE_ACCOUNT_ID set in the environment (per Juan's
  workspace setup notes) and an authenticated `wrangler login` session for
  the Cloudflare account that owns the warrantos-verify Pages project. This
  script does not set or store credentials; it only reads CLOUDFLARE_ACCOUNT_ID
  from the caller's environment and warns if it is absent.

.NOTES
  Run from anywhere; paths resolve relative to this script's location, not
  the caller's working directory.

.EXAMPLE
  $env:CLOUDFLARE_ACCOUNT_ID = '<your-account-id>'
  ./deploy/deploy-verifier.ps1
#>

$ErrorActionPreference = "Stop"

$repoRoot   = Split-Path -Parent $PSScriptRoot
$sourceFile = Join-Path $repoRoot "web\verify.html"
$deployDir  = Join-Path $PSScriptRoot "verifier"
$indexFile  = Join-Path $deployDir "index.html"
$hashFile   = Join-Path $PSScriptRoot "verifier-sha256.txt"

if (-not (Test-Path -LiteralPath $sourceFile)) {
    Write-Error "Source not found: $sourceFile"
    exit 1
}
if (-not (Test-Path -LiteralPath $indexFile)) {
    Write-Error "Deploy copy not found: $indexFile`nCopy web/verify.html to deploy/verifier/index.html first (see deploy/README.md)."
    exit 1
}

# --- Drift guard -------------------------------------------------------
# deploy/verifier/index.html must be an exact, unmodified copy of
# web/verify.html. If it has drifted, someone edited one without the
# other and the deploy would ship a page that no longer matches the
# reviewed, tested source in web/.
$sourceHash = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash
$indexHash  = (Get-FileHash -LiteralPath $indexFile -Algorithm SHA256).Hash

if ($sourceHash -ne $indexHash) {
    Write-Error @"
Drift detected: deploy/verifier/index.html no longer matches web/verify.html.
  web/verify.html            sha256: $sourceHash
  deploy/verifier/index.html sha256: $indexHash

Refusing to deploy. Re-copy web/verify.html to deploy/verifier/index.html
(no edits) and re-run this script.
"@
    exit 1
}

Write-Host "Drift guard passed: deploy/verifier/index.html matches web/verify.html." -ForegroundColor Green

# --- Recompute and publish the digest -----------------------------------
$digest = $indexHash.ToLower()
$hashLine = "sha256:$digest"
Set-Content -LiteralPath $hashFile -Value $hashLine -NoNewline -Encoding ascii
Write-Host "Wrote $hashFile"
Write-Host "  $hashLine"
Write-Host "Publish this digest next to the download link (see deploy/README.md)."

# --- Required environment ------------------------------------------------
if (-not $env:CLOUDFLARE_ACCOUNT_ID) {
    Write-Warning "CLOUDFLARE_ACCOUNT_ID is not set in this session."
    Write-Warning "  `$env:CLOUDFLARE_ACCOUNT_ID = '<your-cloudflare-account-id>'"
}
Write-Host "Wrangler also needs an authenticated session: run 'wrangler login' once if you have not."

# --- Deploy ----------------------------------------------------------------
Write-Host "Deploying $deployDir to Cloudflare Pages project 'warrantos-verify'..."
wrangler pages deploy $deployDir --project-name warrantos-verify
