param(
    [string]$ConfigPath = "config/public_ws_capture.json"
)

$ErrorActionPreference = "Stop"

function ConvertTo-LocalPath {
    param([string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }
    return (Join-Path -Path (Get-Location).Path -ChildPath $Path)
}

$configFullPath = ConvertTo-LocalPath $ConfigPath
$config = Get-Content -LiteralPath $configFullPath -Raw | ConvertFrom-Json
$projectRoot = (Resolve-Path -LiteralPath (Join-Path (Split-Path -Parent $configFullPath) "..")).Path
$workspaceValue = [string]$config.workspace
$workspace = if ([string]::IsNullOrWhiteSpace($workspaceValue) -or $workspaceValue -eq ".") {
    $projectRoot
} elseif ([System.IO.Path]::IsPathRooted($workspaceValue)) {
    $workspaceValue
} else {
    (Resolve-Path -LiteralPath (Join-Path $projectRoot $workspaceValue)).Path
}
$taskName = [string]$config.task_name
$interval = [int]$config.task_interval_minutes
$manager = Join-Path $workspace "scripts\public_ws_capture_manager.ps1"
$daemon = Join-Path $workspace "scripts\public_ws_capture_daemon.ps1"

if (-not (Test-Path -LiteralPath $manager)) {
    throw "Manager script not found: $manager"
}
if (-not (Test-Path -LiteralPath $daemon)) {
    throw "Daemon script not found: $daemon"
}

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$manager`" -Mode ensure -ConfigPath `"$configFullPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $workspace

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$repeatTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $interval) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger @($logonTrigger, $repeatTrigger) `
        -Settings $settings `
        -Principal $principal `
        -Description "Keeps trading-strategy public WS capture alive, updates JSON/MD agent manifests, exports sidecar after first window, and starts 72h capture." `
        -Force | Out-Null

    Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, TaskPath | ConvertTo-Json -Compress
    exit 0
} catch {
    $schedulerError = $_.Exception.Message
}

$startupDir = [Environment]::GetFolderPath("Startup")
if ([string]::IsNullOrWhiteSpace($startupDir)) {
    throw "Could not locate Startup folder after scheduled task failure: $schedulerError"
}

$launcher = Join-Path $startupDir "TradingStrategyPublicWSCapture.vbs"
$daemonArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$daemon`" -ConfigPath `"$configFullPath`" -IntervalMinutes $interval"
$vbsCommand = "powershell.exe $daemonArgs"
$vbs = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "$($vbsCommand.Replace("""", """"""))", 0, False
"@
Set-Content -LiteralPath $launcher -Value $vbs -Encoding ASCII

$existingDaemon = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*public_ws_capture_daemon.ps1*" } |
    Select-Object -First 1

if ($null -eq $existingDaemon) {
    Start-Process -FilePath "powershell.exe" -ArgumentList $daemonArgs -WorkingDirectory $workspace -WindowStyle Hidden | Out-Null
}

[pscustomobject]@{
    method = "startup_folder_daemon"
    scheduler_error = $schedulerError
    startup_launcher = $launcher
    daemon = $daemon
    interval_minutes = $interval
    task_name = $taskName
} | ConvertTo-Json -Compress
