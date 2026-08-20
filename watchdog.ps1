$ErrorActionPreference = 'Continue'
$bridgeRoot = $PSScriptRoot
$dataDir = Join-Path $bridgeRoot 'data'; $logsDir = Join-Path $bridgeRoot 'logs'
$bridgePidFile = Join-Path $dataDir 'bridge.pid'; $watchdogPidFile = Join-Path $dataDir 'watchdog.pid'; $stopFlag = Join-Path $dataDir 'stop.requested'; $logFile = Join-Path $logsDir 'watchdog.log'
$script = Join-Path $bridgeRoot 'app\bridge.py'
New-Item -ItemType Directory -Force -Path $dataDir,$logsDir | Out-Null
Set-Content -LiteralPath $watchdogPidFile -Value $PID -Encoding ascii
function Write-WatchdogLog([string]$message) { Add-Content -LiteralPath $logFile -Encoding utf8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" }
function Find-Python {
    if ($env:CODEX_BRIDGE_PYTHON -and (Test-Path -LiteralPath $env:CODEX_BRIDGE_PYTHON -PathType Leaf)) { return $env:CODEX_BRIDGE_PYTHON }
    $bundled = Join-Path $bridgeRoot 'runtime\python\python.exe'; if (Test-Path -LiteralPath $bundled -PathType Leaf) { return $bundled }
    $codexRuntime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'; if (Test-Path -LiteralPath $codexRuntime -PathType Leaf) { return $codexRuntime }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue; if ($command) { return $command.Source }
    throw 'Python was not found. Install Python 3.11+ or set CODEX_BRIDGE_PYTHON.'
}
try {
    $pythonExe = Find-Python; Write-WatchdogLog "Watchdog started. Python=$pythonExe"
    while (-not (Test-Path -LiteralPath $stopFlag)) {
        $process = Start-Process -FilePath $pythonExe -ArgumentList @($script) -WorkingDirectory $bridgeRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logsDir 'stdout.log') -RedirectStandardError (Join-Path $logsDir 'stderr.log') -PassThru
        Set-Content -LiteralPath $bridgePidFile -Value $process.Id -Encoding ascii; Write-WatchdogLog "Bridge started. PID=$($process.Id)"
        Wait-Process -Id $process.Id -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $bridgePidFile -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $stopFlag) { break }
        Write-WatchdogLog 'Bridge exited unexpectedly. Restarting in 5 seconds.'; Start-Sleep -Seconds 5
    }
    Write-WatchdogLog 'Stop requested. Watchdog exited.'
} catch { Write-WatchdogLog "Watchdog error: $($_.Exception.Message)" } finally { Remove-Item -LiteralPath $watchdogPidFile -Force -ErrorAction SilentlyContinue }
