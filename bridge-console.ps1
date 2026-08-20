$ErrorActionPreference = 'SilentlyContinue'
$Host.UI.RawUI.WindowTitle = 'Codex Feishu Bridge Console'

$bridgeRoot = $PSScriptRoot
$pidFile = Join-Path $bridgeRoot 'data\bridge.pid'
$startScript = Join-Path $bridgeRoot 'start-bridge.ps1'
$stopScript = Join-Path $bridgeRoot 'stop-bridge.ps1'
$dashboard = 'http://127.0.0.1:8765/'

function Get-BridgeStatus {
    $running = $false
    $bridgePid = $null
    if (Test-Path -LiteralPath $pidFile) {
        $bridgePid = [int](Get-Content -LiteralPath $pidFile)
        $running = [bool](Get-Process -Id $bridgePid -ErrorAction SilentlyContinue)
    }
    $desktopRunning = [bool](Get-Process -Name 'ChatGPT' -ErrorAction SilentlyContinue)
    $mode = 'UNKNOWN'
    $modeColor = 'DarkYellow'
    if ($running) {
        try {
            $status = Invoke-RestMethod -Uri ($dashboard + 'api/status') -TimeoutSec 3
            if ($status.mode -eq 'desktop') {
                $mode = 'DESKTOP MODE - Codex app has priority; Feishu is read-only'
                $modeColor = 'Yellow'
            } else {
                $mode = 'MOBILE MODE - Feishu can run Codex tasks'
                $modeColor = 'Green'
            }
        } catch {
            $mode = 'Bridge is starting; status is not ready'
        }
    } elseif ($desktopRunning) {
        $mode = 'Bridge OFF; Codex app is running'
    } else {
        $mode = 'Bridge OFF; Codex app is not running'
    }
    [pscustomobject]@{ Running=$running; Pid=$bridgePid; Mode=$mode; ModeColor=$modeColor; Desktop=$desktopRunning }
}

function Show-Screen {
    Clear-Host
    $status = Get-BridgeStatus
    Write-Host '====================================================' -ForegroundColor Cyan
    Write-Host '            CODEX FEISHU BRIDGE CONSOLE' -ForegroundColor Cyan
    Write-Host '====================================================' -ForegroundColor Cyan
    Write-Host ''
    if ($status.Running) {
        Write-Host "  BRIDGE: ON    PID: $($status.Pid)" -ForegroundColor Green
    } else {
        Write-Host '  BRIDGE: OFF' -ForegroundColor Red
    }
    Write-Host "  MODE:   $($status.Mode)" -ForegroundColor $status.ModeColor
    Write-Host ("  CODEX APP: " + $(if ($status.Desktop) {'RUNNING'} else {'NOT RUNNING'})) -ForegroundColor $(if ($status.Desktop) {'Yellow'} else {'DarkGray'})
    Write-Host "  UI:     $dashboard" -ForegroundColor DarkCyan
    Write-Host ''
    Write-Host '  [1] Start bridge'
    Write-Host '  [2] Stop bridge'
    Write-Host '  [3] Open read-only UI'
    Write-Host '  [4] Refresh status'
    Write-Host '  [5] View recent logs'
    Write-Host '  [6] Enable Windows auto-start'
    Write-Host '  [7] Disable Windows auto-start'
    Write-Host '  [0] Exit console (bridge keeps running)' -ForegroundColor DarkGray
    Write-Host ''
}

while ($true) {
    Show-Screen
    $choice = Read-Host 'Select'
    switch ($choice) {
        '1' {
            $current = Get-BridgeStatus
            if (-not $current.Running) {
                Write-Host 'Starting bridge...' -ForegroundColor Cyan
                powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript -NoBrowser
                Start-Sleep -Seconds 4
            }
        }
        '2' {
            Write-Host 'Stopping bridge...' -ForegroundColor Cyan
            powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript
            Start-Sleep -Seconds 2
        }
        '3' { Start-Process $dashboard }
        '4' { }
        '5' {
            Clear-Host
            Write-Host 'Recent bridge logs:' -ForegroundColor Cyan
            Write-Host ''
            Get-Content -LiteralPath (Join-Path $bridgeRoot 'logs\bridge.log') -Encoding utf8 -Tail 30
            Write-Host ''
            Read-Host 'Press Enter to return'
        }
        '6' { & (Join-Path $bridgeRoot 'set-autostart.ps1') Enable; Start-Sleep -Seconds 2 }
        '7' { & (Join-Path $bridgeRoot 'set-autostart.ps1') Disable; Start-Sleep -Seconds 2 }
        '0' { exit 0 }
        default { Start-Sleep -Milliseconds 300 }
    }
}
