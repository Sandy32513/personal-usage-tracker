# Personal Usage Tracker V3 - Uninstallation Script
# Run this script as Administrator to remove the service

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Personal Usage Tracker V3 - Uninstaller" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Check for admin rights
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

Write-Host "Running as Administrator..." -ForegroundColor Green
Write-Host ""

# Navigate to script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir
Write-Host "Working directory: $scriptDir" -ForegroundColor Gray

$serviceName = "PersonalUsageTrackerV3"

# Check if service exists
Write-Host "[1/4] Checking for service..." -ForegroundColor Cyan
$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

if (-not $service) {
    Write-Host "Service '$serviceName' not found." -ForegroundColor Yellow
    Write-Host "Service may already be uninstalled." -ForegroundColor Yellow
} else {
    # Stop service
    Write-Host "[2/4] Stopping service..." -ForegroundColor Cyan
    if ($service.Status -eq 'Running') {
        Stop-Service -Name $serviceName -Force
        Start-Sleep -Seconds 3
        Write-Host "Service stopped." -ForegroundColor Green
    } else {
        Write-Host "Service already stopped." -ForegroundColor Yellow
    }
    
    # Remove service
    Write-Host "[3/4] Removing service..." -ForegroundColor Cyan
    sc.exe delete $serviceName | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Service removed successfully." -ForegroundColor Green
    } else {
        Write-Host "Failed to remove service. May require manual removal." -ForegroundColor Red
    }
}

# Clean up data files (optional, ask user)
Write-Host "[4/4] Cleanup..." -ForegroundColor Cyan

$answer = Read-Host "Delete logs, queue data, and exports? (y/N)"
if ($answer.ToLower() -eq 'y') {
    Remove-Item -Path "data" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "logs" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "exports" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Data files removed." -ForegroundColor Green
} else {
    Write-Host "Data files preserved." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "UNINSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service removed: $serviceName" -ForegroundColor White
Write-Host ""
Write-Host "Note: The executable (dist\PersonalUsageTrackerV3.exe) remains." -ForegroundColor Gray
Write-Host "You may delete the entire v3-tracker folder manually." -ForegroundColor Gray
Write-Host ""