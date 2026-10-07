<#
.SYNOPSIS
  Back up Ego Labs while it runs: the database and every stored file (videos, results, exports) go into
  backups\<date>_<time>\ as database.dump and files.tgz. Copy that folder somewhere else (another disk,
  cloud storage) to keep it safe. Restoring is in docs/deploy.md.

.EXAMPLE
  .\scripts\backup.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$values = @{}
if (Test-Path .env) {
  foreach ($line in Get-Content .env) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { $values[$matches[1]] = $matches[2].Trim('"', "'") }
  }
}
$user = if ($values["POSTGRES_USER"]) { $values["POSTGRES_USER"] } else { "egolabs" }
$db = if ($values["POSTGRES_DB"]) { $values["POSTGRES_DB"] } else { "egolabs" }

$dir = Join-Path (Join-Path (Get-Location) "backups") (Get-Date -Format "yyyy-MM-dd_HHmm")
New-Item -ItemType Directory -Force $dir | Out-Null

Write-Host "Backing up the database..."
# pg_dump writes inside the container and the file is copied out, so PowerShell never re-encodes it.
docker compose exec -T postgres pg_dump -U $user -d $db --format=custom -f /tmp/egolabs-backup.dump
if ($LASTEXITCODE -ne 0) { throw "The database backup failed. Is the stack running (docker compose ps)?" }
docker compose cp postgres:/tmp/egolabs-backup.dump (Join-Path $dir "database.dump")
if ($LASTEXITCODE -ne 0) { throw "Copying the database backup out of the container failed." }
docker compose exec -T postgres rm -f /tmp/egolabs-backup.dump | Out-Null

Write-Host "Backing up stored files (this can take a while with many videos)..."
docker run --rm -v egolabs_minio-data:/data:ro -v "${dir}:/backup" alpine tar czf /backup/files.tgz -C /data .
if ($LASTEXITCODE -ne 0) { throw "The file backup failed." }

Write-Host "Backup saved in $dir" -ForegroundColor Green
Get-ChildItem $dir | Format-Table Name, @{ Label = "Size (MB)"; Expression = { [math]::Round($_.Length / 1MB, 1) } } -AutoSize
