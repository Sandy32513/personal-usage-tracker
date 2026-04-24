# Personal Usage Tracker V3 - Installation Script
# Run this script as Administrator to install the service

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Personal Usage Tracker V3 - Installer" -ForegroundColor Cyan
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

# Stop service if already installed
Write-Host "[1/6] Checking for existing service..." -ForegroundColor Cyan
$serviceName = "PersonalUsageTrackerV3"
$existingService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

if ($existingService) {
    Write-Host "Service already exists. Stopping and removing..." -ForegroundColor Yellow
    Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    sc.exe delete $serviceName | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "Existing service removed." -ForegroundColor Green
}

# Navigate to script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $projectRoot
Write-Host "Working directory: $projectRoot" -ForegroundColor Gray

# Build the executable
Write-Host ""
Write-Host "[2/8] Building executable with PyInstaller..." -ForegroundColor Cyan
Write-Host "Note: This requires Python and PyInstaller to be installed" -ForegroundColor Yellow

if (Test-Path "dist\PersonalUsageTrackerV3.exe") {
    Write-Host "Existing EXE found, skipping build..." -ForegroundColor Yellow
} else {
    # Run PyInstaller (requires Python environment)
    Write-Host "Running: pyinstaller .\build_exe.spec" -ForegroundColor Gray
    $buildResult = pyinstaller .\build_exe.spec 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build failed. Ensure PyInstaller is installed: pip install pyinstaller" -ForegroundColor Red
        Write-Host $buildResult -ForegroundColor Gray
        exit 1
    }
    
    Write-Host "Build successful!" -ForegroundColor Green
}

# Path to the built exe
$exePath = "dist\PersonalUsageTrackerV3.exe"
if (-not (Test-Path $exePath)) {
    Write-Host "ERROR: Executable not found at $exePath" -ForegroundColor Red
    exit 1
}

Write-Host "Executable: $exePath" -ForegroundColor Green
Write-Host ""

# Install the service
Write-Host "[3/8] Setting up data directories..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "data" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "exports" | Out-Null
Write-Host "Directories created: data, logs, exports" -ForegroundColor Green
Write-Host ""

# Install the service
Write-Host "[4/8] Installing Windows Service..." -ForegroundColor Cyan
Write-Host "Configuring service with least-privilege account..." -ForegroundColor Gray

# Use NETWORK SERVICE (least privilege built-in account)
# Alternative: Use dedicated local user if you prefer
$serviceAccount = "NT AUTHORITY\NETWORK SERVICE"
$absoluteExePath = (Resolve-Path $exePath).Path

sc.exe create $serviceName binPath= "`"$absoluteExePath`"" start= auto obj= $serviceAccount DisplayName= "Personal Usage Tracker V3" | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create service!" -ForegroundColor Red
    exit 1
}

Write-Host "Service created with account: $serviceAccount" -ForegroundColor Green
Write-Host ""

# Add service recovery configuration
Write-Host "[5/8] Configuring service recovery..." -ForegroundColor Cyan
sc.exe failure $serviceName reset= 86400 actions= restart/5000/restart/15000/reboot/60000 | Out-Null
Write-Host "Service recovery configured: restart on failure" -ForegroundColor Green
Write-Host ""

# Configure delayed auto-start
Write-Host "[6/8] Configuring delayed auto-start..." -ForegroundColor Cyan
sc.exe config $serviceName start= delayed-auto | Out-Null
Write-Host "Delayed auto-start configured" -ForegroundColor Green
Write-Host ""

# Set service description
Write-Host "[7/8] Setting service description..." -ForegroundColor Cyan
sc.exe description $serviceName "Tracks application usage and browser activity for productivity analytics. Runs as background Windows Service." | Out-Null
Write-Host "Description set." -ForegroundColor Green
Write-Host ""

# Start the service
Write-Host "[8/8] Starting the service..." -ForegroundColor Cyan
Start-Service -Name $serviceName
Start-Sleep -Seconds 3

$svc = Get-Service -Name $serviceName
Write-Host "Service status: $($svc.Status)" -ForegroundColor Green
Write-Host ""

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service Name: $serviceName" -ForegroundColor White
Write-Host "Status: $($svc.Status)" -ForegroundColor White
Write-Host ""
Write-Host "Management Commands:" -ForegroundColor Cyan
Write-Host "  .\install_service.ps1      - Install/Reinstall service" -ForegroundColor Gray
Write-Host "  .\uninstall_service.ps1    - Remove service" -ForegroundColor Gray
Write-Host "  Get-Service $serviceName   - Check status" -ForegroundColor Gray
Write-Host "  Start-Service $serviceName - Start service" -ForegroundColor Gray
Write-Host "  Stop-Service $serviceName  - Stop service" -ForegroundColor Gray
Write-Host ""
Write-Host "Logs: .\logs\tracker.log" -ForegroundColor Gray
Write-Host "Queue DB: .\data\queue.db" -ForegroundColor Gray
Write-Host "Exports: .\exports\" -ForegroundColor Gray
Write-Host ""
Write-Host "To verify, check Windows Services (services.msc)" -ForegroundColor Yellow
Write-Host ""
