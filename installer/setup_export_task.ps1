# Personal Usage Tracker V3 - Setup CSV Export Task Scheduler
# Creates a Windows Scheduled Task to run CSV export every 10 minutes
# NOTE: This script is DEPRECATED. The service now handles CSV exports automatically.
# Run this script as Administrator

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "CSV Export Task Scheduler Setup" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "WARNING: This scheduled task is DEPRECATED." -ForegroundColor Yellow
Write-Host "The Personal Usage Tracker service now handles CSV exports automatically." -ForegroundColor Yellow
Write-Host "To manually export CSV, use: python -m app.main export" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
exit 0
# Check admin rights
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    exit 1
}

Write-Host "Running as Administrator..." -ForegroundColor Green
Write-Host ""

# Navigate to script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir\..
Write-Host "Project directory: $pwd" -ForegroundColor Gray
Write-Host ""

$taskName = "PersonalUsageTrackerV3-CSVExport"
$taskDescription = "Exports usage data from SQL Server to CSV every 10 minutes"
$pythonPath = (Get-Command python).Source

if (-not $pythonPath) {
    Write-Host "ERROR: Python not found in PATH" -ForegroundColor Red
    Write-Host "Install Python 3.9+ from python.org" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Python found: $pythonPath" -ForegroundColor Green
Write-Host ""

# Path to export script
$exportScript = "$pwd\app\exporter\export_task.py"

if (-not (Test-Path $exportScript)) {
    Write-Host "ERROR: Export script not found at $exportScript" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Export script: $exportScript" -ForegroundColor Green
Write-Host ""

# Check if task already exists
Write-Host "[1/3] Checking for existing scheduled task..." -ForegroundColor Cyan
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Host "Task '$taskName' already exists." -ForegroundColor Yellow
    $answer = Read-Host "Remove and recreate? (y/N)"
    if ($answer.ToLower() -eq 'y') {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Existing task removed." -ForegroundColor Green
    } else {
        Write-Host "Exiting without changes." -ForegroundColor Yellow
        exit 0
    }
}

# Create the task
Write-Host "[2/3] Creating scheduled task..." -ForegroundColor Cyan

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$exportScript`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 365)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable

try {
    Register-ScheduledTask -TaskName $taskName `
        -Description $taskDescription `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Force | Out-Null
    
    Write-Host "Scheduled task created successfully." -ForegroundColor Green
}
catch {
    Write-Host "ERROR: Failed to create scheduled task: $_" -ForegroundColor Red
    Write-Host "Alternative: Use Task Scheduler GUI to create task manually" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Verify
Write-Host "[3/3] Verifying task..." -ForegroundColor Cyan
$task = Get-ScheduledTask -TaskName $taskName
Write-Host "Task Name: $($task.TaskName)" -ForegroundColor Green
Write-Host "State: $($task.State)"
Write-Host "Triggers: $($task.Triggers.Count) (repeats every 10 minutes)"
Write-Host "Next Run: $($task.Triggers[0].StartBoundary)"
Write-Host ""

Write-Host "======================================" -ForegroundColor Green
Write-Host "TASK SCHEDULER SETUP COMPLETE!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host ""
Write-Host "The CSV export will run automatically every 10 minutes." -ForegroundColor Cyan
Write-Host "First run scheduled for: $($task.Triggers[0].StartBoundary)" -ForegroundColor Gray
Write-Host ""
Write-Host "To view task: Task Scheduler (taskschd.msc) → Task Scheduler Library → PersonalUsageTrackerV3-CSVExport" -ForegroundColor Gray
Write-Host "To run manually: Start-ScheduledTask -TaskName $taskName" -ForegroundColor Gray
Write-Host ""
Write-Host "Exports will appear in: .\exports\app_usage.csv and .\exports\web_usage.csv" -ForegroundColor Yellow
Write-Host ""