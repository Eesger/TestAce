# daily-sync.ps1 — Runs every day automatically via Task Scheduler
# Stap 1: Birdclaw haalt nieuwe bookmarks op via browser cookies
# Stap 2: Onze pipeline verwerkt ze (artikelen, ideeën, Notion)

param(
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot)
)

$logFile = Join-Path $ProjectDir "data\sync.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Log($msg) {
    $line = "[$timestamp] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

# Zorg dat de data map bestaat
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir "data") | Out-Null

Log "=== Dagelijkse sync gestart ==="

# --- Stap 1: Birdclaw bookmark sync ---
Log "Birdclaw: bookmarks ophalen..."
try {
    $result = & birdclaw jobs sync-bookmarks 2>&1
    Log "Birdclaw: $result"
} catch {
    Log "WAARSCHUWING: Birdclaw sync mislukt: $_"
    Log "Zorg dat je browser open is en je ingelogd bent op x.com"
}

# --- Stap 2: Pipeline verwerking via Docker ---
Log "Pipeline: artikelen, ideeën en Notion bijwerken..."
Set-Location $ProjectDir

$dockerRunning = docker info 2>&1 | Select-String "Server Version"
if ($dockerRunning) {
    docker compose run --rm archiver xarchiver sync 2>&1 | ForEach-Object { Log $_ }
} else {
    Log "WAARSCHUWING: Docker is niet actief. Start Docker Desktop en probeer opnieuw."
}

Log "=== Sync klaar ==="
