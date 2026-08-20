$ErrorActionPreference = 'Stop'
$targetDir = Join-Path $PSScriptRoot 'app'
$packagesRoot = 'C:\Program Files\WindowsApps'
$package = Get-ChildItem -LiteralPath $packagesRoot -Directory -Filter 'OpenAI.Codex_*_x64__2p2nqsd0c76g0' |
    Sort-Object { [version](($_.Name -split '_')[1]) } -Descending |
    Select-Object -First 1
if (-not $package) { throw 'Cannot find the installed Codex package.' }
$sourceDir = Join-Path $package.FullName 'app\resources'
$files = @(
    'codex.exe',
    'codex-code-mode-host.exe',
    'codex-command-runner.exe',
    'codex-windows-sandbox-setup.exe',
    'rg.exe'
)
foreach ($name in $files) {
    $source = Join-Path $sourceDir $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing Codex runtime component: $name" }
    $destinationName = if ($name -eq 'codex.exe') { 'codex-app-server.exe' } else { $name }
    Copy-Item -LiteralPath $source -Destination (Join-Path $targetDir $destinationName) -Force
}
Set-Content -LiteralPath (Join-Path $targetDir 'runtime-version.txt') -Value $package.Name -Encoding ascii
