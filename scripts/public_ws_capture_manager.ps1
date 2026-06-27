param(
    [ValidateSet("ensure", "status")]
    [string]$Mode = "ensure",
    [string]$ConfigPath = "config/public_ws_capture.json",
    [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"

function Get-UtcStamp {
    return [datetime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Read-JsonFile {
    param([string]$Path)
    return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
}

function ConvertTo-LocalPath {
    param([string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }
    return (Join-Path -Path (Get-Location).Path -ChildPath $Path)
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $tempPath = Join-Path $directory (".{0}.tmp-{1}" -f (Split-Path -Leaf $Path), [guid]::NewGuid().ToString("N"))
    try {
        [System.IO.File]::WriteAllText($tempPath, $Content, $encoding)
        Move-Item -LiteralPath $tempPath -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-EngineCommand {
    param([string[]]$CommandArgs, [string]$LogPath)
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $allArgs = @($script:PythonPrefix) + @($CommandArgs)
    & $script:Python @allArgs *> $LogPath
    $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 1 }
    $ErrorActionPreference = $oldPreference
    return $exitCode
}

function New-SessionId {
    param([string]$Prefix)
    return ("{0}-{1}" -f $Prefix, [datetime]::UtcNow.ToString("yyyyMMdd-HHmmss"))
}

function Update-CaptureManifest {
    param(
        [object]$Config,
        [object]$Inventory,
        [string]$Action,
        [string]$Reason,
        [string]$SessionId = "",
        [Nullable[int]]$ProcessId = $null,
        [string]$Command = ""
    )

    $manifestPath = ConvertTo-LocalPath $Config.paths.manifest
    $manifestDir = Split-Path -Parent $manifestPath
    New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null

    if (Test-Path -LiteralPath $manifestPath) {
        $manifest = Read-JsonFile $manifestPath
        if ($null -eq $manifest.events) {
            $manifest | Add-Member -MemberType NoteProperty -Name events -Value @()
        }
        $manifest.policy = [pscustomobject]@{
            public_only = $true
            private_keys_required = $false
            live_orders_allowed = $false
            raw_stream_storage = "sqlite"
            agent_control_files = @(
                "PLAN_STATUS.json",
                "outputs/data/strict-v3-data-inventory.json",
                "outputs/public-ws/capture_manifest.json",
                "outputs/public-ws/capture_coverage.json",
                "outputs/public-ws/README.md",
                "docs/public_ws_capture.md",
                "config/public_ws_capture.json"
            )
            no_loose_output_rule = "Put new capture logs under outputs/public-ws/logs and summarize state in this manifest."
        }
    } else {
        $manifest = [pscustomobject]@{
            artifact_type = "public_ws_capture_manifest"
            version = 1
            owner = "scripts/public_ws_capture_manager.ps1"
            updated_at_utc = $null
            policy = [pscustomobject]@{
                public_only = $true
                private_keys_required = $false
                live_orders_allowed = $false
                raw_stream_storage = "sqlite"
                agent_control_files = @(
                    "PLAN_STATUS.json",
                    "outputs/data/strict-v3-data-inventory.json",
                    "outputs/public-ws/capture_manifest.json",
                    "outputs/public-ws/capture_coverage.json",
                    "outputs/public-ws/README.md",
                    "docs/public_ws_capture.md",
                    "config/public_ws_capture.json"
                )
                no_loose_output_rule = "Put new capture logs under outputs/public-ws/logs and summarize state in this manifest."
            }
            active = $null
            paths = $null
            task_scheduler = $null
            events = @()
        }
    }

    $capture = $null
    if ($null -ne $Inventory) {
        $capture = $Inventory.forward_public_ws_capture
    }

    $manifest.updated_at_utc = Get-UtcStamp
    $updatedAtUtc = $manifest.updated_at_utc
    $manifest.active = [pscustomobject]@{
        inventory_status = if ($null -ne $Inventory) { $Inventory.status } else { "unavailable" }
        session_id = if ($null -ne $capture) { $capture.session_id } else { "" }
        capture_status = if ($null -ne $capture) { $capture.status } else { "" }
        observed_seconds = if ($null -ne $capture) { $capture.observed_seconds } else { 0 }
        stale = if ($null -ne $capture) { $capture.stale } else { $true }
        latest_activity_at_utc = if ($null -ne $capture) { $capture.latest_activity_at_utc } else { "" }
        target_window_ready = if ($null -ne $capture) { $capture.target_window_ready } else { $false }
        strong_window_ready = if ($null -ne $capture) { $capture.strong_window_ready } else { $false }
    }
    $manifest.paths = [pscustomobject]@{
        db = $Config.db
        inventory = $Config.paths.inventory
        sidecar = $Config.paths.sidecar
        logs_dir = $Config.paths.logs_dir
        readme = $Config.paths.readme
        coverage = $Config.paths.coverage
    }
    $manifest.task_scheduler = [pscustomobject]@{
        task_name = $Config.task_name
        interval_minutes = $Config.task_interval_minutes
        manager = "scripts/public_ws_capture_manager.ps1"
        installer = "scripts/install_public_ws_capture_autostart.ps1"
        active_mode = "startup_folder_daemon"
        fallback_reason = "ScheduledTask access can be denied in no-admin sessions; Startup launches scripts/public_ws_capture_daemon.ps1 at user login."
    }

    $event = [pscustomobject]@{
        at_utc = Get-UtcStamp
        action = $Action
        reason = $Reason
        session_id = $SessionId
        pid = $ProcessId
        command = $Command
    }

    $events = @($manifest.events) + @($event)
    if ($events.Count -gt 100) {
        $events = $events[($events.Count - 100)..($events.Count - 1)]
    }
    $manifest.events = $events
    Write-Utf8NoBom -Path $manifestPath -Content ($manifest | ConvertTo-Json -Depth 8)

    Write-CoverageReport -Config $Config -Inventory $Inventory -UpdatedAtUtc $updatedAtUtc
}

function Write-CoverageReport {
    param(
        [object]$Config,
        [object]$Inventory,
        [string]$UpdatedAtUtc
    )

    $coveragePath = ConvertTo-LocalPath $Config.paths.coverage
    $coverageDir = Split-Path -Parent $coveragePath
    New-Item -ItemType Directory -Force -Path $coverageDir | Out-Null

    $capture = $null
    if ($null -ne $Inventory) {
        $capture = $Inventory.forward_public_ws_capture
    }

    $latestActivity = ""
    $stale = $true
    $staleSeconds = $null
    $observedSeconds = 0
    $sessionId = ""
    $captureStatus = "unavailable"
    $targetReady = $false
    $strongReady = $false
    $streamCounts = @{}
    $streamRequirements = @()

    if ($null -ne $capture) {
        $latestActivity = [string]$capture.latest_activity_at_utc
        $stale = [bool]$capture.stale
        $staleSeconds = $capture.stale_seconds
        $observedSeconds = [int]$capture.observed_seconds
        $sessionId = [string]$capture.session_id
        $captureStatus = [string]$capture.status
        $targetReady = [bool]$capture.target_window_ready
        $strongReady = [bool]$capture.strong_window_ready
        $streamCounts = $capture.stream_counts
        $streamRequirements = $capture.stream_requirements
    }

    $unavailableRanges = @()
    if (Test-Path -LiteralPath $coveragePath) {
        try {
            $priorCoverage = Read-JsonFile $coveragePath
            if ($null -ne $priorCoverage.unavailable_ranges) {
                $unavailableRanges = @($priorCoverage.unavailable_ranges)
            }
        } catch {
            $unavailableRanges = @()
        }
    }
    if ($stale -and -not [string]::IsNullOrWhiteSpace($latestActivity)) {
        $newRange = [pscustomobject]@{
            from_utc = $latestActivity
            to_utc = $UpdatedAtUtc
            reason = "capture_stale_or_laptop_asleep_offline"
            affected_streams = $Config.streams
            treatment = "missing_unavailable_not_zero"
        }
        $lastRange = $unavailableRanges | Select-Object -Last 1
        if ($null -ne $lastRange -and [string]$lastRange.from_utc -eq $latestActivity -and [string]$lastRange.reason -eq $newRange.reason) {
            $lastRange.to_utc = $UpdatedAtUtc
        } else {
            $unavailableRanges += $newRange
        }
    }

    $coverage = [pscustomobject]@{
        artifact_type = "public_ws_capture_coverage"
        version = 1
        updated_at_utc = $UpdatedAtUtc
        source_manifest = $Config.paths.manifest
        source_inventory = $Config.paths.inventory
        active_session = [pscustomobject]@{
            session_id = $sessionId
            status = $captureStatus
            observed_seconds = $observedSeconds
            stale = $stale
            stale_seconds = $staleSeconds
            latest_activity_at_utc = $latestActivity
            target_window_ready = $targetReady
            strong_window_ready = $strongReady
            stream_counts = $streamCounts
            stream_requirements = $streamRequirements
        }
        gap_policy = [pscustomobject]@{
            can_collect_when_laptop_closed_or_asleep = $false
            laptop_closed_or_asleep_result = "live_websocket_gap"
            missed_force_order_or_book_ticker_backfill = "unavailable"
            missed_mark_price_backfill = "limited_derived_or_rest_klines_only_not_tick_equivalent"
            ohlcv_backfill = "archive_or_rest_backfill_allowed_when_inventory_records_source"
            never_zero_fill_missing_liquidations = $true
            use_only_observed_windows_for_liquidation_sidecar = $true
        }
        unavailable_ranges = $unavailableRanges
        downstream_use = [pscustomobject]@{
            use_for_strategy_improvement_claim = $false
            ws_first_window_ready_for_sidecar_export = ($targetReady -and -not $stale)
            if_false_reason = "Requires observed continuous WS window, sidecar export, 72h capture status, and paper/executor evidence in PLAN_STATUS.json."
            allowed_current_use = "capture_health_and_future_evidence_only"
            forbidden_use = @(
                "zero_fill_missing_liquidations",
                "treat_laptop_off_gap_as_market_quiet",
                "claim_strategy_improvement_from_partial_ws_capture",
                "replace sealed validation or paper executor evidence"
            )
        }
    }

    Write-Utf8NoBom -Path $coveragePath -Content ($coverage | ConvertTo-Json -Depth 10)
}

function Write-CaptureReadme {
    param([object]$Config)
    $readmePath = ConvertTo-LocalPath $Config.paths.readme
    $readmeDir = Split-Path -Parent $readmePath
    New-Item -ItemType Directory -Force -Path $readmeDir | Out-Null
    $content = @"
# Public WS Capture Data

Agent entry files:

1. `PLAN_STATUS.json`
2. `outputs/data/strict-v3-data-inventory.json`
3. `outputs/public-ws/capture_manifest.json`
4. `outputs/public-ws/capture_coverage.json`
5. `config/public_ws_capture.json`
6. `docs/public_ws_capture.md`

Raw telemetry stays in `outputs/public-ws/public_stream.sqlite`.
Final liquidation sidecar is `outputs/public-ws/liquidation_notional.csv`.
Logs from managed capture go under `outputs/public-ws/logs/`.

When the laptop is closed, asleep, powered off, or offline, live WS data cannot be captured. Those intervals are gaps, not zero-volume truth. The current gap report is `outputs/public-ws/capture_coverage.json`.

Do not create ad hoc capture folders unless `config/public_ws_capture.json` is revised first.
Do not treat missing liquidation events outside an observed WS window as zero.
Do not claim strategy improvement from this data until the evidence gates in `PLAN_STATUS.json` pass.
If `outputs/public-ws/capture_manifest.json` records `start_first_capture_failed` or `start_strong_capture_failed`, treat capture as blocked until a later manager run records a healthy active session.
"@
    Write-Utf8NoBom -Path $readmePath -Content $content
}

function Test-StrongCaptureAlreadyActive {
    param([object]$Inventory, [object]$Config)
    if ($null -eq $Inventory) {
        return $false
    }
    $capture = $Inventory.forward_public_ws_capture
    if ($null -eq $capture) {
        return $false
    }
    $session = [string]$capture.session_id
    $stale = [bool]$capture.stale
    $prefix = if ($null -ne $Config.strong_session_detection_prefix) { [string]$Config.strong_session_detection_prefix } else { [string]$Config.session_prefix_strong }
    return ($session.StartsWith($prefix) -and -not $stale)
}

function Test-StrongCaptureExists {
    param([object]$Config)
    $db = ([string]$Config.db).Replace("/", "\")
    $prefix = if ($null -ne $Config.strong_session_detection_prefix) { [string]$Config.strong_session_detection_prefix } else { [string]$Config.session_prefix_strong }
    $check = @"
import sqlite3
db = r"$db"
prefix = "$prefix"
con = sqlite3.connect(db)
cur = con.cursor()
row = cur.execute(
    "select session_id, status, heartbeat_at_utc from paper_sessions where session_id like ? order by started_at_utc desc limit 1",
    (prefix + "%",),
).fetchone()
healthy = False
if row:
    status = str(row[1])
    if status == "completed":
        healthy = True
    elif status == "running" and row[2]:
        from datetime import datetime, timezone
        heartbeat = datetime.fromisoformat(str(row[2]).replace("Z", "+00:00"))
        healthy = (datetime.now(timezone.utc) - heartbeat).total_seconds() <= 300
print("1" if healthy else "0")
"@
    $checkArgs = @($script:PythonPrefix) + @("-")
    $count = $check | & $script:Python @checkArgs
    return (($count | Select-Object -Last 1) -as [int]) -gt 0
}

function ConvertTo-CmdArgument {
    param([string]$Value)
    if ($Value -match '^[A-Za-z0-9_@%+=:,./\\-]+$') {
        return $Value
    }
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Start-CaptureProcess {
    param([object]$Config, [string]$SessionId, [int]$DurationSeconds)

    $logsDir = ConvertTo-LocalPath $Config.paths.logs_dir
    New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
    $outLog = Join-Path $logsDir "$SessionId.out.log"
    $errLog = Join-Path $logsDir "$SessionId.err.log"

    $args = @($script:PythonPrefix) + @(
        "-m", "engine.app.cli", "paper-ws-run",
        "--db", ([string]$Config.db).Replace("/", "\"),
        "--capture-only",
        "--session-id", $SessionId
    )
    foreach ($symbol in $Config.symbols) {
        $args += @("--symbol", [string]$symbol)
    }
    foreach ($stream in $Config.streams) {
        $args += @("--stream-kind", [string]$stream)
    }
    $args += @(
        "--max-duration-seconds", [string]$DurationSeconds,
        "--no-message-timeout-seconds", [string]$Config.no_message_timeout_seconds,
        "--heartbeat-interval-seconds", [string]$Config.heartbeat_interval_seconds
    )

    $commandParts = @((ConvertTo-CmdArgument -Value $script:Python))
    foreach ($arg in $args) {
        $commandParts += (ConvertTo-CmdArgument -Value $arg)
    }
    $script:LastCaptureCommand = $commandParts -join " "
    return Start-Process `
        -FilePath $script:Python `
        -ArgumentList $args `
        -WorkingDirectory (Get-Location).Path `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -WindowStyle Hidden `
        -PassThru
}

function Test-CaptureProcessStarted {
    param([System.Diagnostics.Process]$Process, [object]$Config, [string]$SessionId)
    $seconds = if ($null -ne $Config.post_start_healthcheck_seconds) { [int]$Config.post_start_healthcheck_seconds } else { 12 }
    if ($seconds -gt 0) {
        Start-Sleep -Seconds $seconds
    }
    if ($Process.HasExited) {
        return $false
    }

    $db = ([string]$Config.db).Replace("/", "\")
    $symbolsJson = @($Config.symbols) | ConvertTo-Json -Compress
    $check = @"
import json, sqlite3
con = sqlite3.connect(r"$db")
symbols = [str(value).lower() for value in json.loads(r'''$symbolsJson''')]
required = [f"{symbol}@{kind}" for symbol in symbols for kind in ("bookTicker", "markPrice@1s")]
counts = dict(con.execute(
    "select stream_name, count(*) from paper_stream_events where session_id=? group by stream_name",
    ("$SessionId",),
).fetchall())
print("1" if all(int(counts.get(name, 0)) > 0 for name in required) else "0")
"@
    $checkArgs = @($script:PythonPrefix) + @("-")
    $healthy = $check | & $script:Python @checkArgs
    return (($healthy | Select-Object -Last 1) -as [int]) -eq 1
}

function Stop-CaptureSession {
    param([object]$Config, [string]$SessionId, [string]$Reason)
    if ([string]::IsNullOrWhiteSpace($SessionId)) {
        return
    }
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -like "*paper-ws-run*" -and
            $_.CommandLine -like "*--session-id $SessionId*"
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    $db = ([string]$Config.db).Replace("/", "\")
    $mark = @"
import sqlite3
from datetime import datetime, timezone
con = sqlite3.connect(r"$db")
now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
con.execute(
    "update paper_sessions set status='stale_incomplete', stopped_at_utc=coalesce(stopped_at_utc, ?), heartbeat_at_utc=? where session_id=? and status='running'",
    (now, now, "$SessionId"),
)
con.commit()
"@
    $markArgs = @($script:PythonPrefix) + @("-")
    $mark | & $script:Python @markArgs | Out-Null
}

function Refresh-Inventory {
    param([object]$Config)
    $refreshLog = Join-Path (ConvertTo-LocalPath $Config.paths.logs_dir) "strict-data-collect-post-start.log"
    $refreshExit = Invoke-EngineCommand -CommandArgs @("-m", "engine.app.cli", "strict-data-collect", "--sync-plan-status", "--export-liquidations-when-ready") -LogPath $refreshLog
    if ($refreshExit -ne 0) {
        return $null
    }
    return Read-JsonFile (ConvertTo-LocalPath $Config.paths.inventory)
}

$configFullPath = ConvertTo-LocalPath $ConfigPath
$config = Read-JsonFile $configFullPath
$projectRoot = (Resolve-Path -LiteralPath (Join-Path (Split-Path -Parent $configFullPath) "..")).Path
$workspaceValue = [string]$config.workspace
$workspace = if ([string]::IsNullOrWhiteSpace($workspaceValue) -or $workspaceValue -eq ".") {
    $projectRoot
} elseif ([System.IO.Path]::IsPathRooted($workspaceValue)) {
    $workspaceValue
} else {
    (Resolve-Path -LiteralPath (Join-Path $projectRoot $workspaceValue)).Path
}
Set-Location -LiteralPath $workspace
$pythonValue = [string]$config.python
$script:PythonPrefix = @($config.python_args | ForEach-Object { [string]$_ })
if ([System.IO.Path]::IsPathRooted($pythonValue)) {
    $script:Python = $pythonValue
    if (-not (Test-Path -LiteralPath $script:Python)) {
        throw "Configured Python interpreter not found: $script:Python"
    }
} elseif ($pythonValue -match '[\\/]') {
    $script:Python = Join-Path $workspace $pythonValue
    if (-not (Test-Path -LiteralPath $script:Python)) {
        throw "Configured Python interpreter not found: $script:Python"
    }
} else {
    $script:Python = $pythonValue
    if ($null -eq (Get-Command $script:Python -ErrorAction SilentlyContinue)) {
        throw "Configured Python command not found: $script:Python"
    }
}
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\TradingStrategyPublicWSCaptureManager", [ref]$createdNew)
if (-not $createdNew) {
    exit 0
}
New-Item -ItemType Directory -Force -Path (ConvertTo-LocalPath $config.paths.logs_dir) | Out-Null
Write-CaptureReadme -Config $config

$strictLog = Join-Path (ConvertTo-LocalPath $config.paths.logs_dir) "strict-data-collect-last.log"
$exitCode = Invoke-EngineCommand -CommandArgs @("-m", "engine.app.cli", "strict-data-collect", "--sync-plan-status", "--export-liquidations-when-ready") -LogPath $strictLog
if ($exitCode -ne 0) {
    Update-CaptureManifest -Config $config -Inventory $null -Action "strict_data_collect_failed" -Reason "strict-data-collect exit code $exitCode"
    exit $exitCode
}

$inventory = Read-JsonFile (ConvertTo-LocalPath $config.paths.inventory)
$capture = $inventory.forward_public_ws_capture
$session = [string]$capture.session_id
$stale = [bool]$capture.stale
$status = [string]$inventory.status
$targetReady = [bool]$capture.target_window_ready
$requiredStreamsReady = [bool]$capture.required_streams_ready
$maxRequiredGap = if ($null -ne $capture.max_required_stream_gap_seconds) { [int]$capture.max_required_stream_gap_seconds } else { $null }
$maxAllowedGap = if ($null -ne $capture.max_observed_gap_seconds) { [int]$capture.max_observed_gap_seconds } else { 300 }
$routeHealthy = $requiredStreamsReady -and $null -ne $maxRequiredGap -and $maxRequiredGap -le $maxAllowedGap

if ($Mode -eq "status") {
    Update-CaptureManifest -Config $config -Inventory $inventory -Action "status_only" -Reason "Status refresh only"
    exit 0
}

if ($ForceRestart -and -not [string]::IsNullOrWhiteSpace($session)) {
    Stop-CaptureSession -Config $config -SessionId $session -Reason "forced_restart"
    $stale = $true
    $routeHealthy = $false
    $status = "start_forward_capture"
}

if (Test-StrongCaptureAlreadyActive -Inventory $inventory -Config $config) {
    Update-CaptureManifest -Config $config -Inventory $inventory -Action "noop_strong_capture_running" -Reason "Strong 72h capture already active" -SessionId $session
    exit 0
}

if ((-not $stale) -and $routeHealthy -and ($status -eq "monitor_forward_capture" -or $status -eq "strong_forward_capture")) {
    if ($targetReady -and -not (Test-StrongCaptureAlreadyActive -Inventory $inventory -Config $config)) {
        $sidecarLog = Join-Path (ConvertTo-LocalPath $config.paths.logs_dir) "export-liquidation-sidecar-last.log"
        $exportExit = Invoke-EngineCommand -CommandArgs @(
            "-m", "engine.app.cli", "export-forceorder-liquidations",
            "--db", ([string]$config.db).Replace("/", "\"),
            "--session-id", $session,
            "--output", ([string]$config.paths.sidecar).Replace("/", "\"),
            "--timeframe", "1Hour",
            "--include-observed-zero-buckets"
        ) -LogPath $sidecarLog
        if ($exportExit -ne 0) {
            Update-CaptureManifest -Config $config -Inventory $inventory -Action "sidecar_export_failed" -Reason "export-forceorder-liquidations exit code $exportExit" -SessionId $session
            exit $exportExit
        }
        if (Test-StrongCaptureExists -Config $config) {
            Update-CaptureManifest -Config $config -Inventory $inventory -Action "noop_strong_capture_exists" -Reason "A 72h public WS capture already exists; not starting duplicate" -SessionId $session
            exit 0
        }
        $strongSession = New-SessionId -Prefix ([string]$config.session_prefix_strong)
        $process = Start-CaptureProcess -Config $config -SessionId $strongSession -DurationSeconds ([int]$config.strong_capture_seconds)
        if (-not (Test-CaptureProcessStarted -Process $process -Config $config -SessionId $strongSession)) {
            Update-CaptureManifest -Config $config -Inventory $inventory -Action "start_strong_capture_failed" -Reason "72h capture process exited during post-start healthcheck with code $($process.ExitCode)" -SessionId $strongSession -ProcessId $process.Id -Command $script:LastCaptureCommand
            exit $process.ExitCode
        }
        $postStartInventory = Refresh-Inventory -Config $config
        Update-CaptureManifest -Config $config -Inventory $(if ($null -ne $postStartInventory) { $postStartInventory } else { $inventory }) -Action "started_strong_capture" -Reason "Target first window ready; sidecar exported; 72h capture started" -SessionId $strongSession -ProcessId $process.Id -Command $script:LastCaptureCommand
        exit 0
    }

    Update-CaptureManifest -Config $config -Inventory $inventory -Action "noop_active_capture" -Reason "Current capture is active and not stale" -SessionId $session
    exit 0
}

if ((-not $stale) -and (-not $routeHealthy) -and -not [string]::IsNullOrWhiteSpace($session)) {
    Stop-CaptureSession -Config $config -SessionId $session -Reason "required_stream_health_failed"
} elseif ($stale -and -not [string]::IsNullOrWhiteSpace($session)) {
    Stop-CaptureSession -Config $config -SessionId $session -Reason "capture_stale"
}

$newSession = New-SessionId -Prefix ([string]$config.session_prefix_first)
$newProcess = Start-CaptureProcess -Config $config -SessionId $newSession -DurationSeconds ([int]$config.first_capture_seconds)
if (-not (Test-CaptureProcessStarted -Process $newProcess -Config $config -SessionId $newSession)) {
    Update-CaptureManifest -Config $config -Inventory $inventory -Action "start_first_capture_failed" -Reason "First-window capture process exited during post-start healthcheck with code $($newProcess.ExitCode)" -SessionId $newSession -ProcessId $newProcess.Id -Command $script:LastCaptureCommand
    exit $newProcess.ExitCode
}
$postStartInventory = Refresh-Inventory -Config $config
Update-CaptureManifest -Config $config -Inventory $(if ($null -ne $postStartInventory) { $postStartInventory } else { $inventory }) -Action "started_first_capture" -Reason "No healthy first-window capture was active" -SessionId $newSession -ProcessId $newProcess.Id -Command $script:LastCaptureCommand
exit 0
