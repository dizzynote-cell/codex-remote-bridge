param([ValidateSet('Enable','Disable','Status')][string]$Action='Status')
$ErrorActionPreference = 'Stop'; $bridgeRoot = $PSScriptRoot; $taskName = 'Codex Remote Bridge'
if ($Action -eq 'Enable') {
    $taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $bridgeRoot 'tray.ps1')`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Settings $settings -Description 'Start Codex Remote Bridge after Windows sign-in.' -Force | Out-Null
    'Auto-start enabled.'
} elseif ($Action -eq 'Disable') { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; 'Auto-start disabled.' }
else { $task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue; if($task){"Auto-start: $($task.State)"}else{'Auto-start: disabled'} }
