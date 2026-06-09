# Sync canonical data/ -> frontend deploy directory (one-way only).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $Root "data"
$Dst = Join-Path $Root "slave_coder\src\shared_data"
New-Item -ItemType Directory -Force -Path $Dst | Out-Null
Copy-Item (Join-Path $Src "master_data.json"), (Join-Path $Src "events_data.json") $Dst -Force
Write-Host "Synced data/*.json -> slave_coder/src/shared_data/ at $(Get-Date -Format o)"
