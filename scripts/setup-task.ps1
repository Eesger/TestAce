# setup-task.ps1 — Registreert daily-sync.ps1 als Windows Taakplanner-taak
# Eenmalig uitvoeren als Administrator (rechtermuisknop > Als administrator uitvoeren)

param(
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName  = "XArchiverDailySync",
    [string]$RunAt     = "08:00"
)

$ErrorActionPreference = "Stop"

$script = Join-Path $PSScriptRoot "daily-sync.ps1"

if (-not (Test-Path $script)) {
    Write-Error "Script niet gevonden: $script"
    exit 1
}

# Verwijder oude versie als die bestaat
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Bestaande taak '$TaskName' verwijderen..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute   "powershell.exe" `
    -Argument  "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -ProjectDir `"$ProjectDir`""

$trigger = New-ScheduledTaskTrigger -Daily -At $RunAt

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances   IgnoreNew `
    -ExecutionTimeLimit  (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -RunLevel    Highest `
    -Description "Dagelijkse X bookmark sync: Birdclaw + Docker pipeline" | Out-Null

Write-Host ""
Write-Host "Taak '$TaskName' aangemaakt — dagelijks om $RunAt"
Write-Host "  Script : $script"
Write-Host "  Project: $ProjectDir"
Write-Host ""
Write-Host "Controleer  : Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Nu uitvoeren: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Logbestand  : $ProjectDir\data\sync.log"
