param(
    [string]$ConfigPath = "config/public_ws_capture.json",
    [int]$IntervalMinutes = 15,
    [switch]$Once
)

$ErrorActionPreference = "Continue"

$manager = Join-Path $PSScriptRoot "public_ws_capture_manager.ps1"
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $workspace

function Get-LogDir {
    param([string]$Config)
    try {
        $cfg = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
        $dir = [string]$cfg.paths.logs_dir
        if ([System.IO.Path]::IsPathRooted($dir)) {
            return $dir
        }
        return (Join-Path $workspace $dir)
    } catch {
        return (Join-Path $workspace "outputs\public-ws\logs")
    }
}

$logDir = Get-LogDir -Config $ConfigPath
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$daemonLog = Join-Path $logDir "public-ws-capture-daemon.log"

function Write-DaemonLog {
    param([string]$Message)
    $stamp = [datetime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    Add-Content -LiteralPath $daemonLog -Value "$stamp $Message"
}

do {
    Write-DaemonLog "manager run start"
    $lastLog = Join-Path $logDir "public-ws-capture-daemon-last-manager.log"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $manager -Mode ensure -ConfigPath $ConfigPath *> $lastLog
    $exitCode = $LASTEXITCODE
    Write-DaemonLog "manager run exit_code=$exitCode"

    if ($Once) {
        exit $exitCode
    }

    Start-Sleep -Seconds ($IntervalMinutes * 60)
} while ($true)
