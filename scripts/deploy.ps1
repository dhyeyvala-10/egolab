<#
.SYNOPSIS
  Put Ego Labs online through a Cloudflare Tunnel, or update it: checks .env, gets the latest code, and starts
  the production stack (docker-compose.yml + docker-compose.prod.yml). See docs/deploy.md.

.EXAMPLE
  .\scripts\deploy.ps1              # deploy, or update to the latest code
  .\scripts\deploy.ps1 -NewSecrets  # print fresh random secrets to paste into .env
  .\scripts\deploy.ps1 -NoPull      # start without git pull (e.g. testing local changes)
  .\scripts\deploy.ps1 -CheckOnly   # only check .env
#>
param([switch]$NewSecrets, [switch]$NoPull, [switch]$CheckOnly)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function New-Secret {
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  # Hex: safe inside the database URL and in .env without quoting.
  ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

if ($NewSecrets) {
  Write-Host "Paste these into .env (replacing the old lines):"
  "JWT_SECRET=$(New-Secret)"
  "POSTGRES_PASSWORD=$(New-Secret)"
  "MINIO_ROOT_PASSWORD=$(New-Secret)"
  exit 0
}

if (-not (Test-Path .env)) { throw "There's no .env file here. Copy .env.example to .env and fill it in (docs/deploy.md)." }

$values = @{}
foreach ($line in Get-Content .env) {
  if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
    $values[$matches[1]] = $matches[2].Trim('"', "'")
  }
}

$problems = @()
foreach ($key in @("APP_DOMAIN", "FILES_DOMAIN", "CLOUDFLARE_TUNNEL_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "OWNER_EMAIL")) {
  if (-not $values[$key]) { $problems += "$key is empty" }
}
foreach ($key in @("APP_DOMAIN", "FILES_DOMAIN")) {
  if ($values[$key] -match '^(https?://)|/') { $problems += "$key must be just the name, like app.example.com (no https:// or /)" }
}
$devDefaults = @{
  JWT_SECRET          = "dev-only-insecure-jwt-secret-change-me"
  POSTGRES_PASSWORD   = "egolabs"
  MINIO_ROOT_PASSWORD = "egolabs-dev-secret"
}
foreach ($key in $devDefaults.Keys) {
  $value = $values[$key]
  if (-not $value -or $value -eq $devDefaults[$key] -or $value.Length -lt 32) {
    $problems += "$key must be a random value of at least 32 characters (run .\scripts\deploy.ps1 -NewSecrets)"
  }
}
foreach ($email in (($values["OWNER_EMAIL"] -split ",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
  if ($email -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
    $problems += "OWNER_EMAIL: '$email' isn't an email address (list admins' Google emails, separated by commas)"
  }
}
if ($values["PASSWORD_LOGIN"] -eq "true") { $problems += "PASSWORD_LOGIN must not be true online (it is for local scripts only)" }

if ($problems.Count -gt 0) {
  Write-Host "Fix these in .env first:" -ForegroundColor Red
  foreach ($p in $problems) { Write-Host "  - $p" -ForegroundColor Red }
  exit 1
}
Write-Host ".env looks good: https://$($values['APP_DOMAIN']) (files at https://$($values['FILES_DOMAIN'])), admins $($values['OWNER_EMAIL'])" -ForegroundColor Green
if ($CheckOnly) { exit 0 }

if (-not $NoPull) {
  git pull --ff-only
  if ($LASTEXITCODE -ne 0) { throw "git pull failed; see the message above." }
}

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
if ($LASTEXITCODE -ne 0) {
  throw "Starting the stack failed. See what went wrong with: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail 100"
}
Write-Host ""
Write-Host "Ego Labs is running. Open https://$($values['APP_DOMAIN'])" -ForegroundColor Green
