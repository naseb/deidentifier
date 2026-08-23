<#
Removes the de-identification watcher scheduled task installed by
install_watcher_task.ps1.

Run this once, manually, from PowerShell:
    powershell -ExecutionPolicy Bypass -File uninstall_watcher_task.ps1
#>

$TaskName = "Lab Deidentifier Watcher"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "Removed scheduled task: $TaskName"
    } catch {
        Write-Error "Failed to remove the scheduled task: $($_.Exception.Message)"
        Write-Error "This is almost always caused by PowerShell not running elevated. Right-click PowerShell (or Windows Terminal) and choose 'Run as administrator', then re-run this script."
        exit 1
    }
} else {
    Write-Host "No scheduled task named '$TaskName' was found."
}
