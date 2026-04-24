# Personal Usage Tracker V3 - Complete Uninstall Script
# Removes both Windows Service and User Agent scheduled task

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Personal Usage Tracker V3 - Uninstaller" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Check for admin rights
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    exit 1
}

$serviceName = "PersonalUsageTrackerV3"
$taskName = "PersonalUsageTrackerAgent"

# Step 1: Stop and remove service
Write-Host "[1/3] Removing Windows Service..." -ForegroundColor Cyan
$existingService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existingService) {
    Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    sc.exe delete $serviceName | Out-Null
    Write-Host "Service '$serviceName' removed." -ForegroundColor Green
} else {
    Write-Host "Service '$serviceName' not found." -ForegroundColor Yellow
}

# Step 2: Remove scheduled task
Write-Host "[2/3] Removing User Agent scheduled task..." -ForegroundColor Cyan
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Task '$taskName' removed." -ForegroundColor Green
} else {
    Write-Host "Task '$taskName' not found." -ForegroundColor Yellow
}

# Step 3: Done
Write-Host "[3/3] Cleanup complete." -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: Data directories were NOT removed (in case you want to keep logs/exports):" -ForegroundColor Yellow
Write-Host "  $env:ProgramData\PersonalUsageTracker\" -ForegroundColor Gray
Write-Host ""
Write-Host "To remove data as well, delete that folder manually." -ForegroundColor Gray
Write-Host ""
Write-Host "Uninstall complete!" -ForegroundColor Green