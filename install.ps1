# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
function Ask([string]$label,[string]$default='') { $suffix=if($default){" [$default]"}else{''}; $value=Read-Host "$label$suffix"; if([string]::IsNullOrWhiteSpace($value)){return $default}; return $value.Trim() }
function Clean([string]$value) { if($value -match "[`r`n]"){throw 'Configuration values cannot contain line breaks.'}; return $value }
Clear-Host
Write-Host 'Codex Remote Bridge - Setup' -ForegroundColor Cyan
Write-Host 'About 10-20 minutes, 6 steps:'
Write-Host '  1. Check Windows, Python and Codex'
Write-Host '  2. Choose Feishu-only or Feishu + Web'
Write-Host '  3. Configure the Feishu app'
Write-Host '  4. Configure project and large-file folders'
Write-Host '  5. Configure domain/server (Web mode only)'
Write-Host '  6. Install dependencies and auto-start'
Read-Host 'Press Enter to begin'
Write-Host '[1/6] Environment check' -ForegroundColor Cyan
$python=Get-Command python.exe -ErrorAction SilentlyContinue; if(-not $python){throw 'Python 3.11+ was not found in PATH.'}; & $python.Source --version
$codexPackage=Get-ChildItem -LiteralPath 'C:\Program Files\WindowsApps' -Directory -Filter 'OpenAI.Codex_*_x64__2p2nqsd0c76g0' -ErrorAction SilentlyContinue | Select-Object -First 1
if(-not $codexPackage){throw 'The Windows Codex app was not found. Install and sign in to Codex first.'}
Write-Host '[2/6] Mode' -ForegroundColor Cyan
$mode=Ask 'Enter 1 for Feishu-only, 2 for Feishu + Web' '1'; if($mode -notin @('1','2')){throw 'Mode must be 1 or 2.'}
Write-Host '[3/6] Feishu app' -ForegroundColor Cyan
$appId=Clean (Ask 'FEISHU_APP_ID'); $appSecret=Clean (Ask 'FEISHU_APP_SECRET'); if(-not $appId -or -not $appSecret){throw 'Feishu App ID and App Secret are required.'}
Write-Host '[4/6] Local folders' -ForegroundColor Cyan
$projectsRoot=Clean (Ask 'Projects root folder' (Join-Path $env:USERPROFILE 'Documents\CodexProjects')); $largeFileDir=Clean (Ask 'Large-file sync folder (optional)' ''); $standaloneDir=Join-Path $root 'data\standalone'
New-Item -ItemType Directory -Force -Path $projectsRoot,$standaloneDir | Out-Null; if($largeFileDir){New-Item -ItemType Directory -Force -Path $largeFileDir | Out-Null}
$historyUrl='';$syncToken='';$sshHost='';$sshKey='';$domain=''
if($mode -eq '2'){
 Write-Host '[5/6] Web server' -ForegroundColor Cyan; Write-Host 'For mainland China users, a lightweight Hong Kong server is commonly a practical option.'
 $domain=Clean (Ask 'Public HTTPS base URL, e.g. https://bridge.example.com'); $syncToken=Clean (Ask 'Long random sync token'); $historyUrl="$($domain.TrimEnd('/'))/api/sync"; $sshHost=Clean (Ask 'Optional SSH host' ''); $sshKey=Clean (Ask 'Optional SSH private-key path' '')
}else{Write-Host '[5/6] Server configuration skipped.' -ForegroundColor DarkGray}
New-Item -ItemType Directory -Force -Path (Join-Path $root 'config') | Out-Null
@("FEISHU_APP_ID=$appId","FEISHU_APP_SECRET=$appSecret","CODEX_HISTORY_URL=$historyUrl","CODEX_HISTORY_SYNC_TOKEN=$syncToken","CODEX_HISTORY_SSH_HOST=$sshHost","CODEX_HISTORY_SSH_KEY=$sshKey","CODEX_LARGE_FILE_DIR=$largeFileDir","CODEX_PROJECTS_ROOT=$projectsRoot","CODEX_STANDALONE_DIR=$standaloneDir") | Set-Content -LiteralPath (Join-Path $root 'config\.env') -Encoding utf8
if($mode -eq '2'){
 @("FEISHU_APP_ID=$appId","FEISHU_APP_SECRET=$appSecret","FEISHU_OWNER_OPEN_ID=replace_after_first_owner_binding","SYNC_TOKEN=$syncToken","PUBLIC_BASE_URL=$domain","CLIENT_PROJECTS_ROOT=$projectsRoot","CLIENT_STANDALONE_DIR=$standaloneDir","CODEX_HISTORY_DB=/opt/codex-history/data/history.db") | Set-Content -LiteralPath (Join-Path $root 'cloud\.env.generated') -Encoding utf8
 Write-Host 'Generated cloud/.env.generated. Upload securely; never commit it.' -ForegroundColor Yellow
}
Write-Host '[6/6] Dependencies and auto-start' -ForegroundColor Cyan
& $python.Source -m pip install -r (Join-Path $root 'requirements.txt'); & (Join-Path $root 'sync-codex-runtime.ps1')
$enableAuto=Ask 'Enable bridge auto-start after Windows sign-in? (Y/N)' 'Y'; if($enableAuto -match '^[Yy]'){& (Join-Path $root 'set-autostart.ps1') Enable}
$installTccli=Ask 'Install Tencent Cloud CLI for optional DNS/server setup? (Y/N)' 'N'; if($installTccli -match '^[Yy]'){& $python.Source -m pip install tccli}
Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',(Join-Path $root 'tray.ps1')) -WindowStyle Hidden
Write-Host 'Setup completed. The tray icon is now running.' -ForegroundColor Green
