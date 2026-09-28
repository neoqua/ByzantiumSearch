<#
.SYNOPSIS
  Stop the Cultural History Analyzer stack (Windows).

.DESCRIPTION
  Stops and removes the containers. SQLite data in .\data and the SearXNG
  settings volume are kept. -Volumes also removes the SearXNG volume
  (.\data is never touched).

  Also terminates a host-mode uvicorn ("app.main:app") if one is still running.
  LM Studio is not managed by this script.

.EXAMPLE
  .\scripts\stop.ps1
  .\scripts\stop.ps1 -Volumes
#>
[CmdletBinding()]
param(
    [switch]$Volumes
)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Log($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "WARN $msg" -ForegroundColor Yellow }

# Host-mode uvicorn started by start.ps1 -HostMode: match the command line
# *and* port 8000 - other projects may run "uvicorn app.main:app" as well.
$uvicorn = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'uvicorn\s+app\.main:app.*--port\s+8000' }
if ($uvicorn) {
    Log 'Stopping host-mode uvicorn (port 8000)'
    foreach ($p in $uvicorn) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { }
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Warn 'docker not found; nothing to stop on the container side.'
    exit 0
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Warn 'Docker daemon is not running; nothing to stop on the container side.'
    exit 0
}

Log 'Stopping containers'
if ($Volumes) { docker compose down --volumes } else { docker compose down }
if ($LASTEXITCODE -ne 0) { Warn 'docker compose down returned an error (see above)' }

Log 'Done. SQLite data kept in .\data'
