# Fetch the newest nightly copy of seed1's service state to this PC (deploy/backup.sh says what is in it:
# the Harbourmaster's memory and threads, the plank and ride records; no wallets, no keys, no chain).
#   powershell -ExecutionPolicy Bypass -File scripts\pull-backup.ps1
# Lands in private\backups, which git ignores. Keeps the newest 30 here. Needs the seed SSH key on this PC.
param(
    [string]$Seed = "seed1.berrychain.link",
    [string]$Key = "$HOME\.ssh\berrychain_seed",
    [int]$Keep = 30
)
$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "private\backups"
New-Item -ItemType Directory -Force $dest | Out-Null

$name = & ssh -i $Key -o BatchMode=yes -o ConnectTimeout=20 "root@$Seed" "readlink /var/backups/berrychain/latest.tar.gz"
if ($LASTEXITCODE -ne 0 -or -not $name) {
    Write-Host "No backup found on $Seed. Has 'bash /opt/berrychain/deploy/backup-setup.sh' been run there?"
    exit 1
}
$name = "$name".Trim()
if ($name -notmatch '^services-[0-9]{8}-[0-9]{6}\.tar\.gz$') {
    Write-Host "Unexpected backup name from ${Seed}: $name"
    exit 1
}
$target = Join-Path $dest $name
if (Test-Path $target) {
    Write-Host "Already have $name"
    exit 0
}
& scp -i $Key -o BatchMode=yes -o ConnectTimeout=20 "root@${Seed}:/var/backups/berrychain/$name" $target
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $target)) {
    Write-Host "Copy failed."
    exit 1
}
Get-ChildItem $dest -Filter "services-*.tar.gz" | Sort-Object Name -Descending | Select-Object -Skip $Keep | Remove-Item -Confirm:$false
$size = [math]::Round((Get-Item $target).Length / 1KB)
Write-Host "Fetched $name ($size KB) to $dest"
