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
# The watchdog stops the Python parent; its RPC child otherwise survives and
# locks the bridge runtime. Match this project's exact executable, not codex.exe.
$bridgeRuntime = [IO.Path]::GetFullPath((Join-Path $bridgeRoot 'app\codex-app-server.exe'))
Get-CimInstance Win32_Process -Filter "Name='codex-app-server.exe'" | Where-Object {
    $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath).Equals($bridgeRuntime,[StringComparison]::OrdinalIgnoreCase)
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
