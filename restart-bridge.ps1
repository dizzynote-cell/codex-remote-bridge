$ErrorActionPreference = 'Stop'
$bridgeRoot = $PSScriptRoot
$envFile = Join-Path $bridgeRoot 'config\.env'
$settings = @{}
if(Test-Path -LiteralPath $envFile){ foreach($line in Get-Content -LiteralPath $envFile -Encoding UTF8){ if($line -match '^\s*([^#=]+)=(.*)$'){$settings[$matches[1].Trim()]=$matches[2].Trim()} } }
& (Join-Path $bridgeRoot 'stop-bridge.ps1')
$syncUrl=$settings['CODEX_HISTORY_URL']; $token=$settings['CODEX_HISTORY_SYNC_TOKEN']
if($syncUrl -and $token){
    try {
        $base=($syncUrl.TrimEnd('/') -replace '/api/sync$','')
        Invoke-RestMethod -Method Post -Uri "$base/api/device/status" -Headers @{Authorization="Bearer $token"} -ContentType 'application/json' -Body (@{state='restarting';seconds=20;message='planned restart'}|ConvertTo-Json) -TimeoutSec 10 | Out-Null
    } catch { Add-Content -LiteralPath (Join-Path $bridgeRoot 'logs\restart.log') -Encoding UTF8 -Value "$(Get-Date -Format o) restart notice failed: $($_.Exception.Message)" }
}
Start-Sleep -Seconds 8
& (Join-Path $bridgeRoot 'start-bridge.ps1') -NoBrowser
