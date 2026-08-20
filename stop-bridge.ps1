$ErrorActionPreference = 'Stop'
$bridgeRoot = $PSScriptRoot
$dataDir = Join-Path $bridgeRoot 'data'
$stopFlag = Join-Path $dataDir 'stop.requested'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Set-Content -LiteralPath $stopFlag -Value (Get-Date).ToString('o') -Encoding ascii
foreach ($name in 'bridge.pid','watchdog.pid') {
    $pidFile = Join-Path $dataDir $name
    if (-not (Test-Path -LiteralPath $pidFile -PathType Leaf)) { continue }
    $targetPid = [int](Get-Content -LiteralPath $pidFile)
    if (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) { Stop-Process -Id $targetPid -Force -ErrorAction Stop }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
