# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$root = $PSScriptRoot
$created = $false
$mutex = [Threading.Mutex]::new($true,'Local\CodexRemoteBridgeTray',[ref]$created)
if(-not $created){exit 0}
$dataDir=Join-Path $root 'data'; $logsDir=Join-Path $root 'logs'; $bridgePidFile=Join-Path $dataDir 'bridge.pid'; $watchdogPidFile=Join-Path $dataDir 'watchdog.pid'
function Is-ProcessRunning($pidFile){if(-not(Test-Path -LiteralPath $pidFile)){return $false};$id=0;if(-not[int]::TryParse((Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue),[ref]$id)){return $false};return [bool](Get-Process -Id $id -ErrorAction SilentlyContinue)}
function New-StatusIcon([Drawing.Color]$color){$bmp=[Drawing.Bitmap]::new(32,32);$g=[Drawing.Graphics]::FromImage($bmp);$g.SmoothingMode='AntiAlias';$g.Clear([Drawing.Color]::Transparent);$brush=[Drawing.SolidBrush]::new($color);$g.FillEllipse($brush,3,3,26,26);$font=[Drawing.Font]::new('Segoe UI',[single]13,[Drawing.FontStyle]::Bold);$white=[Drawing.SolidBrush]::new([Drawing.Color]::White);$g.DrawString('C',$font,$white,7,5);$icon=[Drawing.Icon]::FromHandle($bmp.GetHicon());$white.Dispose();$font.Dispose();$brush.Dispose();$g.Dispose();$bmp.Dispose();return $icon}
$icons=@{}
$icons.on=New-StatusIcon ([Drawing.Color]::FromArgb(52,199,120))
$icons.starting=New-StatusIcon ([Drawing.Color]::FromArgb(245,158,11))
$icons.off=New-StatusIcon ([Drawing.Color]::FromArgb(220,68,68))
$notify=New-Object Windows.Forms.NotifyIcon;$notify.Icon=$icons.off;$notify.Text='Codex Remote Bridge: OFF';$notify.Visible=$true
$menu=New-Object Windows.Forms.ContextMenuStrip
$statusItem=$menu.Items.Add('Status: OFF');$statusItem.Enabled=$false
[void]$menu.Items.Add('-')
$openItem=$menu.Items.Add('Open Web UI');$startItem=$menu.Items.Add('Start Bridge');$restartItem=$menu.Items.Add('Restart Bridge');$stopItem=$menu.Items.Add('Stop Bridge');$logItem=$menu.Items.Add('Open Logs');$autoItem=$menu.Items.Add('Start with Windows');$autoItem.CheckOnClick=$false
[void]$menu.Items.Add('-');$exitItem=$menu.Items.Add('Exit (stop bridge)');$notify.ContextMenuStrip=$menu
function Run-Script($name){Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',(Join-Path $root $name)) -WorkingDirectory $root -WindowStyle Hidden}
$openItem.add_Click({Start-Process 'http://127.0.0.1:8765/'})
$notify.add_DoubleClick({Start-Process 'http://127.0.0.1:8765/'})
$startItem.add_Click({Run-Script 'start-bridge.ps1'})
$restartItem.add_Click({Run-Script 'restart-bridge.ps1'})
$stopItem.add_Click({Run-Script 'stop-bridge.ps1'})
$logItem.add_Click({New-Item -ItemType Directory -Force -Path $logsDir|Out-Null;Start-Process explorer.exe -ArgumentList $logsDir})
$autoItem.add_Click({if($autoItem.Checked){& (Join-Path $root 'set-autostart.ps1') Disable}else{& (Join-Path $root 'set-autostart.ps1') Enable};Start-Sleep -Milliseconds 300;$autoItem.Checked=[bool](Get-ScheduledTask -TaskName 'Codex Remote Bridge' -ErrorAction SilentlyContinue)})
$exitItem.add_Click({$notify.Text='Codex Remote Bridge: STOPPING';$notify.Icon=$icons.starting;& (Join-Path $root 'stop-bridge.ps1');$notify.Visible=$false;[Windows.Forms.Application]::Exit()})
$timer=New-Object Windows.Forms.Timer;$timer.Interval=2500
$timer.add_Tick({$bridge=Is-ProcessRunning $bridgePidFile;$watchdog=Is-ProcessRunning $watchdogPidFile;if($bridge){$notify.Icon=$icons.on;$notify.Text='Codex Remote Bridge: ON';$statusItem.Text='Status: ON';$startItem.Enabled=$false;$restartItem.Enabled=$true;$stopItem.Enabled=$true}elseif($watchdog){$notify.Icon=$icons.starting;$notify.Text='Codex Remote Bridge: STARTING';$statusItem.Text='Status: STARTING';$startItem.Enabled=$false;$restartItem.Enabled=$false;$stopItem.Enabled=$true}else{$notify.Icon=$icons.off;$notify.Text='Codex Remote Bridge: OFF';$statusItem.Text='Status: OFF';$startItem.Enabled=$true;$restartItem.Enabled=$false;$stopItem.Enabled=$false};$autoItem.Checked=[bool](Get-ScheduledTask -TaskName 'Codex Remote Bridge' -ErrorAction SilentlyContinue)})
$timer.Start();Run-Script 'start-bridge.ps1';[Windows.Forms.Application]::Run();$timer.Stop();$notify.Dispose();foreach($icon in $icons.Values){$icon.Dispose()};$mutex.ReleaseMutex();$mutex.Dispose()
