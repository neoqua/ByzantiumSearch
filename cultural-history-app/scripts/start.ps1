<#
.SYNOPSIS
  Start the Cultural History Analyzer stack (Windows).

.DESCRIPTION
  Default (Docker mode): app + SearXNG + OpenSERP run in containers.
  -HostMode:             SearXNG + OpenSERP in containers, app via uvicorn
                         from .\venv (foreground, Ctrl+C to stop the app).
  -NoBuild:              Docker mode without rebuilding the app image.

  LM Studio is not managed by this script: start its Local Server on the host
  (port 1234) or select a remote LLM provider in the web UI.

.EXAMPLE
  .\scripts\start.ps1
  .\scripts\start.ps1 -HostMode
  .\scripts\start.ps1 -NoBuild
#>
[CmdletBinding()]
param(
    [switch]$HostMode,
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$AppUrl      = 'http://localhost:8000'
$SearxngUrl  = 'http://localhost:8888'
$OpenserpUrl = 'http://localhost:7000'
$LmStudioUrl = 'http://localhost:1234/v1/models'

function Log($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "WARN $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "ERROR $msg" -ForegroundColor Red; exit 1 }

function Test-Http($url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch { return $false }
}

function Wait-Http($url, $name, $timeout = 60) {
    Write-Host -NoNewline "    waiting for $name "
    for ($i = 0; $i -lt $timeout; $i++) {
        if (Test-Http $url) { Write-Host ' ok'; return $true }
        Write-Host -NoNewline '.'
        Start-Sleep -Seconds 1
    }
    Write-Host ''
    Warn "$name did not answer at $url within ${timeout}s (check: docker compose logs)"
    return $false
}

function Ensure-SearxngSecret {
    if (-not $env:SEARXNG_SECRET -and (Test-Path '.env')) {
        $line = Get-Content '.env' | Where-Object { $_ -match '^SEARXNG_SECRET=' } | Select-Object -Last 1
        if ($line) {
            $env:SEARXNG_SECRET = $line.Substring('SEARXNG_SECRET='.Length).Trim()
        }
    }
    if (-not $env:SEARXNG_SECRET) {
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $env:SEARXNG_SECRET = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
        Add-Content -Path '.env' -Value "SEARXNG_SECRET=$($env:SEARXNG_SECRET)"
        Log 'Wrote SEARXNG_SECRET into .env (gitignored)'
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Die 'docker not found. Install Docker Desktop first.'
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Die 'Docker daemon is not running. Start Docker Desktop, wait for "Engine running", and retry.'
}

Ensure-SearxngSecret

if (Test-Http $LmStudioUrl) {
    Log "LM Studio detected at $LmStudioUrl"
} else {
    Warn "LM Studio is not answering at $LmStudioUrl. Start its Local Server, or select a remote LLM provider in the UI."
}

if (-not $HostMode) {
    Log 'Starting SearXNG, OpenSERP and app (Docker mode)'
    if ($NoBuild) { docker compose up -d } else { docker compose up -d --build }
    if ($LASTEXITCODE -ne 0) { Die 'docker compose up failed' }

    Wait-Http "$AppUrl/"      'app'      90 | Out-Null
    Wait-Http "$OpenserpUrl/health" 'OpenSERP' 30 | Out-Null
    Wait-Http "$SearxngUrl/"  'SearXNG'  60 | Out-Null

    Write-Host ''
    docker compose ps
    Write-Host ''
    Log "Open $AppUrl"
    Write-Host "    SearXNG:  $SearxngUrl"
    Write-Host "    OpenSERP: $OpenserpUrl"
    Write-Host '    Logs:     docker compose logs -f app'
    Write-Host '    Stop:     .\scripts\stop.ps1  (or scripts\stop.cmd)'
} else {
    Log 'Starting SearXNG and OpenSERP (host mode)'
    docker compose up -d searxng openserp
    if ($LASTEXITCODE -ne 0) { Die 'docker compose up failed' }
    Wait-Http "$OpenserpUrl/health" 'OpenSERP' 30 | Out-Null
    Wait-Http "$SearxngUrl/"  'SearXNG'  60 | Out-Null

    $py = $null
    foreach ($candidate in @('venv\Scripts\python.exe', '.venv\Scripts\python.exe')) {
        if (Test-Path $candidate) { $py = $candidate; break }
    }
    if (-not $py) {
        Log 'No venv found - creating .\venv and installing requirements'
        $sysPy = Get-Command python -ErrorAction SilentlyContinue
        if (-not $sysPy) { Die 'python not found in PATH.' }
        python -m venv venv
        if ($LASTEXITCODE -ne 0) { Die 'venv creation failed' }
        & 'venv\Scripts\python.exe' -m pip install --quiet --upgrade pip
        & 'venv\Scripts\python.exe' -m pip install --quiet -r requirements.txt
        if ($LASTEXITCODE -ne 0) { Die 'pip install failed' }
        $py = 'venv\Scripts\python.exe'
    }

    Write-Host ''
    Log 'Starting app with uvicorn (Ctrl+C stops the app; containers keep running - use scripts\stop.ps1)'
    Write-Host "    Open $AppUrl"
    Write-Host ''
    & $py -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
}
