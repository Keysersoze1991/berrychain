# Register a Windows scheduled task so the miner starts at every logon and
# restarts if it dies. Run once from the repo folder:
#   powershell -ExecutionPolicy Bypass -File scripts\install-miner-task.ps1 -Miner brry1...
param([Parameter(Mandatory = $true)][string]$Miner)
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\mine.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -Miner $Miner" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
Register-ScheduledTask -TaskName "BerryChain Miner" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "BerryChain Miner"
Write-Host "BerryChain Miner task registered and started. Check it: curl http://127.0.0.1:8801/status"
Write-Host "Stop it any time: Stop-ScheduledTask -TaskName 'BerryChain Miner'"
