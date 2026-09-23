# Run a BerryChain mining node on Windows, peered with the seed nodes.
#   powershell -ExecutionPolicy Bypass -File scripts\mine.ps1 -Miner brry1...
# Binds to localhost only; nothing needs to reach this PC. Data in data\miner.
param(
    [Parameter(Mandatory = $true)][string]$Miner,
    [string]$Genesis = "launch\mainnet-genesis.json",
    [string[]]$Peers = @("https://seed1.berrychain.link", "https://seed2.berrychain.link"),
    [int]$Port = 8801
)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$args = @("-m", "berrychain.cli", "node", "--genesis", $Genesis, "--data", "data\miner", "--port", "$Port", "--mine", $Miner)
foreach ($p in $Peers) { $args += @("--peer", $p) }
& python @args
