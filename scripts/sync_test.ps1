# Two-node sync and reorg test. Run from the repo root:  powershell -File scripts/sync_test.ps1
param([string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")
$ErrorActionPreference = "Continue"
$miner = (Get-Content keys/architect.json | ConvertFrom-Json).address
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "berrychain.cli node" } | Stop-Process -Force -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force data -ErrorAction SilentlyContinue

function Start-Node($name, $port, $peer) {
    $args = @("-m", "berrychain.cli", "node", "--genesis", "genesis.json", "--data", "data/$name", "--port", "$port")
    if ($peer) { $args += @("--peer", $peer) }
    $p = Start-Process -FilePath $Python -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput "$name.log" -RedirectStandardError "$name.err"
    Start-Sleep 3
    return $p
}
function Mine($port, $n) {
    (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$port/mine" -Body "{`"miner`":`"$miner`",`"blocks`":$n}" -ContentType application/json).height
}
function Status($port) { Invoke-RestMethod "http://127.0.0.1:$port/status" }

$p1 = Start-Node n1 8801 $null
$h1 = Mine 8801 30
"node1 mined to height $h1"

$p2 = Start-Node n2 8802 "http://127.0.0.1:8801"
Start-Sleep 8
$s1 = Status 8801; $s2 = Status 8802
"initial sync: node2 height $($s2.height), tips match: $($s1.tip_hash -eq $s2.tip_hash)"

# fork: stop node1, node2 mines 2 alone; stop node2, node1 mines 4 alone; restart node2 -> must reorg to node1's longer chain
Stop-Process -Id $p1.Id -Force; Start-Sleep 1
$h2 = Mine 8802 2
Stop-Process -Id $p2.Id -Force; Start-Sleep 1
$p1 = Start-Node n1 8801 $null
$h1 = Mine 8801 4
"fork: node1 at $h1, node2 at $h2"
$p2 = Start-Node n2 8802 "http://127.0.0.1:8801"
Start-Sleep 8
$s1 = Status 8801; $s2 = Status 8802
"after reorg: node2 height $($s2.height), tips match: $($s1.tip_hash -eq $s2.tip_hash)"

# gossip: node2 mines, node1 must receive without polling delay
$h2 = Mine 8802 3
Start-Sleep 3
$s1 = Status 8801
"gossip: node2 at $h2, node1 at $($s1.height)"

Stop-Process -Id $p1.Id, $p2.Id -Force -ErrorAction SilentlyContinue
Get-Content n1.err, n2.err -ErrorAction SilentlyContinue | Select-Object -First 20
Remove-Item -Recurse -Force n1.log, n2.log, n1.err, n2.err, data -ErrorAction SilentlyContinue
