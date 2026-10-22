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
try {
    & (Join-Path $bridgeRoot 'sync-codex-runtime.ps1')
} catch {
    $runtimeFiles = @('codex-app-server.exe','codex-code-mode-host.exe','codex-command-runner.exe','codex-windows-sandbox-setup.exe','rg.exe')
    $missing = @($runtimeFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $bridgeRoot "app\$_") -PathType Leaf) })
    if ($missing.Count) { throw }
    Add-Content -LiteralPath (Join-Path $logsDir 'watchdog.log') -Encoding utf8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Runtime refresh unavailable; starting with existing components. $($_.Exception.Message)"
}
$watchdog = Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',(Join-Path $bridgeRoot 'watchdog.ps1')) -WorkingDirectory $bridgeRoot -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $watchdogPidFile -Value $watchdog.Id -Encoding ascii
Start-Sleep -Seconds 4
if (-not (Get-Process -Id $watchdog.Id -ErrorAction SilentlyContinue)) { throw "桥守护程序启动失败，请查看 $logsDir\watchdog.log" }
if (-not $noBrowser) { Start-Process 'http://127.0.0.1:8765/' }
