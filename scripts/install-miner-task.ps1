# Register a Windows scheduled task so the miner starts at every logon and
# restarts if it dies. Run once from the repo folder (re-run after updates):
#   powershell -ExecutionPolicy Bypass -File scripts\install-miner-task.ps1 -Miner brry1...
# The task runs python.exe directly, so Stop-ScheduledTask really stops mining.
param([Parameter(Mandatory = $true)][string]$Miner,
      [string]$Genesis = "launch\mainnet-genesis.json",
      [string[]]$Peers = @("https://seed1.berrychain.link", "https://seed2.berrychain.link"))
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$argList = "-m berrychain.cli node --genesis `"$Genesis`" --data data\miner --port 8801 --mine $Miner"
foreach ($p in $Peers) { $argList += " --peer $p" }
# stop anything already mining from this folder before (re)registering
Stop-ScheduledTask -TaskName "BerryChain Miner" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "berrychain.cli node" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
$action = New-ScheduledTaskAction -Execute $python -Argument $argList -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -Hidden
Register-ScheduledTask -TaskName "BerryChain Miner" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "BerryChain Miner"
Write-Host "BerryChain Miner task registered and started (runs $python from $root)."
Write-Host "Check it in a minute: curl http://127.0.0.1:8801/status"
Write-Host "Stop it any time:    Stop-ScheduledTask -TaskName 'BerryChain Miner'"
