<#
Installs the de-identification watcher as a Windows Scheduled Task that starts
silently at logon (no console window, ever) and restarts automatically if the
process ever stops.

Run this once, manually, from PowerShell:
    powershell -ExecutionPolicy Bypass -File install_watcher_task.ps1

Re-running it is safe -- it replaces the existing task definition.
#>

$TaskName = "Lab Deidentifier Watcher"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WatcherScript = Join-Path $ScriptDir "watch_and_deidentify.py"

$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    Write-Error "Could not find 'python' on PATH. Install Python and make sure 'Add python.exe to PATH' was checked, then re-run this script."
    exit 1
}
$PythonwExe = $PythonExe -replace "python\.exe$", "pythonw.exe"
if (-not (Test-Path $PythonwExe)) {
    Write-Warning "pythonw.exe not found next to python.exe ($PythonwExe) -- falling back to python.exe, which may briefly flash a console window at logon."
    $PythonwExe = $PythonExe
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing task '$TaskName' before re-creating it..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$Action = New-ScheduledTaskAction -Execute $PythonwExe -Argument "`"$WatcherScript`"" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 0)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -ErrorAction Stop | Out-Null
} catch {
    Write-Error "Failed to register the scheduled task: $($_.Exception.Message)"
    Write-Error "This is almost always caused by PowerShell not running elevated. Right-click PowerShell (or Windows Terminal) and choose 'Run as administrator', then re-run this script."
    exit 1
}

Write-Host "Installed scheduled task: $TaskName"
Write-Host "It will start automatically next time you log in."
Write-Host ""
Write-Host "To start it right now without logging out, run:"
Write-Host "    Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host ""
Write-Host "To check on it later:"
Write-Host "    Get-ScheduledTask -TaskName `"$TaskName`" | Get-ScheduledTaskInfo"
Write-Host "    Get-Content `"$ScriptDir\watcher.log`" -Tail 30"
