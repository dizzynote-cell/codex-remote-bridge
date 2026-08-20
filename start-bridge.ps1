$ErrorActionPreference = 'Stop'
$bridgeRoot = $PSScriptRoot
$dataDir = Join-Path $bridgeRoot 'data'
$logsDir = Join-Path $bridgeRoot 'logs'
$watchdogPidFile = Join-Path $dataDir 'watchdog.pid'
$stopFlag = Join-Path $dataDir 'stop.requested'
$noBrowser = $args -contains '-NoBrowser'
New-Item -ItemType Directory -Force -Path $dataDir,$logsDir | Out-Null
Remove-Item -LiteralPath $stopFlag -Force -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $watchdogPidFile -PathType Leaf) {
    $savedPid = [int](Get-Content -LiteralPath $watchdogPidFile)
    if (Get-Process -Id $savedPid -ErrorAction SilentlyContinue) {
        if (-not $noBrowser) { Start-Process 'http://127.0.0.1:8765/' }
        exit 0
    }
}
& (Join-Path $bridgeRoot 'sync-codex-runtime.ps1')
$watchdog = Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',(Join-Path $bridgeRoot 'watchdog.ps1')) -WorkingDirectory $bridgeRoot -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $watchdogPidFile -Value $watchdog.Id -Encoding ascii
Start-Sleep -Seconds 4
if (-not (Get-Process -Id $watchdog.Id -ErrorAction SilentlyContinue)) { throw "桥守护程序启动失败，请查看 $logsDir\watchdog.log" }
if (-not $noBrowser) { Start-Process 'http://127.0.0.1:8765/' }
