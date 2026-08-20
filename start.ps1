$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = '1'
$bridgeRoot = $PSScriptRoot
& (Join-Path $bridgeRoot 'start-bridge.ps1')
