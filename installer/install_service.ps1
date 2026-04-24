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
#================================================================================
# Personal Usage Tracker V3 - Complete Installation Script
# Installs:
#   1. Windows Service (data pipeline: queue, DB insert, CSV export)
#   2. User Agent (scheduled task - captures app/browser activity)
#================================================================================

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

# Stop & remove existing service if present
$serviceName = "PersonalUsageTrackerV3"
$existingService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "[1/4] Removing existing service..." -ForegroundColor Cyan
    Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    sc.exe delete $serviceName | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "Service removed." -ForegroundColor Green
}

# Navigate to script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $projectRoot
Write-Host "Project root: $projectRoot" -ForegroundColor Gray

# ===================================================================
# STEP 1: Install the Windows Service (data pipeline)
# ===================================================================
Write-Host ""
Write-Host "[2/4] Building and installing Windows Service..." -ForegroundColor Cyan

# Build executable if not present
$exePath = Join-Path $projectRoot "dist\PersonalUsageTrackerV3.exe"
if (-not (Test-Path $exePath)) {
    Write-Host "Building EXE with PyInstaller..." -ForegroundColor Yellow
    pyinstaller --clean --onefile --name PersonalUsageTrackerV3 app\main.py 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build failed. Ensure PyInstaller is installed: pip install pyinstaller" -ForegroundColor Red
        exit 1
    }
    Write-Host "Build successful!" -ForegroundColor Green
} else {
    Write-Host "Using existing EXE: $exePath" -ForegroundColor Green
}

# Create data directories
$baseDir = Join-Path $env:ProgramData "PersonalUsageTracker"
New-Item -ItemType Directory -Force -Path "$baseDir\data" | Out-Null
New-Item -ItemType Directory -Force -Path "$baseDir\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$baseDir\exports" | Out-Null
Write-Host "Directories created: $baseDir" -ForegroundColor Green

# Install the service
Write-Host "Creating Windows Service..." -ForegroundColor Gray
$absoluteExePath = (Resolve-Path $exePath).Path
sc.exe create $serviceName binPath= "`"$absoluteExePath`"" start= auto obj= "NT AUTHORITY\NETWORK SERVICE" DisplayName= "Personal Usage Tracker V3" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create service!" -ForegroundColor Red
    exit 1
}
Write-Host "Service created with account: NT AUTHORITY\NETWORK SERVICE" -ForegroundColor Green

# Service recovery
sc.exe failure $serviceName reset= 86400 actions= restart/5000/restart/15000/reboot/60000 | Out-Null
sc.exe config $serviceName start= delayed-auto | Out-Null
sc.exe description $serviceName "Tracks application usage and browser activity. Runs as background Windows Service. Receives events from user-session agent." | Out-Null

# Start the service
Start-Service -Name $serviceName
Start-Sleep -Seconds 3
$svc = Get-Service -Name $serviceName
Write-Host "Service status: $($svc.Status)" -ForegroundColor Green
Write-Host ""

# ===================================================================
# STEP 2: Install the User Agent (scheduled task - per-user capture)
# ===================================================================
Write-Host "[3/4] Installing User Agent (scheduled task)..." -ForegroundColor Cyan

$taskName = "PersonalUsageTrackerAgent"
$pythonScript = Join-Path $projectRoot "agent.py"

# Find Python executable
$pythonExe = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $pythonExe) {
    $pythonExe = "python.exe"  # hope it's in PATH when task runs
}
Write-Host "Using Python: $pythonExe" -ForegroundColor Gray

# Uninstall existing task if present
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Create scheduled task to run at user logon
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$pythonScript`" --host 127.0.0.1 --port 8766"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\INTERACTIVE" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Personal Usage Tracker - User Session Agent" | Out-Null
Write-Host "Scheduled task '$taskName' created (runs at user logon)" -ForegroundColor Green

# Run the task now (for current user) - will start agent immediately
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 2
Write-Host "Agent task started." -ForegroundColor Green
Write-Host ""

# ===================================================================
# STEP 3: Verify
# ===================================================================
Write-Host "[4/4] Verification..." -ForegroundColor Cyan
Write-Host "Service: $(Get-Service -Name $serviceName | Select-Object -ExpandProperty Status)" -ForegroundColor Green
$taskInfo = Get-ScheduledTask -TaskName $taskName
if ($taskInfo) {
    Write-Host "Agent Task: Installed (Triggers: AtLogOn)" -ForegroundColor Green
} else {
    Write-Host "Agent Task: NOT FOUND" -ForegroundColor Red
}
Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "What was installed:" -ForegroundColor White
Write-Host "  1. Windows Service: $serviceName (data pipeline)" -ForegroundColor Gray
Write-Host "  2. Scheduled Task: $taskName (per-user agent)" -ForegroundColor Gray
Write-Host ""
Write-Host "Data directories:" -ForegroundColor Cyan
Write-Host "  $baseDir\data\queue.db" -ForegroundColor Gray
Write-Host "  $baseDir\logs\" -ForegroundColor Gray
Write-Host "  $baseDir\exports\" -ForegroundColor Gray
Write-Host ""
Write-Host "Management commands:" -ForegroundColor Cyan
Write-Host "  .\installer\install_service.ps1      - Reinstall service + agent" -ForegroundColor Gray
Write-Host "  .\installer\uninstall_service.ps1    - Remove both" -ForegroundColor Gray
Write-Host ""
Write-Host "NOTE: The agent runs in your user session; service runs in background." -ForegroundColor Yellow
Write-Host "Together they provide full foreground window capture." -ForegroundColor Yellow
Write-Host ""
