from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import shutil

from engine.io.artifacts import write_text_atomic
from engine.io.sqlite import connect_sqlite
from engine.memory.store import initialize_memory_db


SYSTEMD_UNIT = """[Unit]
Description=Trading Strategy Phase 9A Paper Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=trading-strategy
Group=trading-strategy
WorkingDirectory=/opt/trading-strategy
EnvironmentFile=/opt/trading-strategy/deploy/env/paper-daemon.env
ExecStart=/usr/bin/python3 -m engine.app.cli paper-daemon --dry-run --db ${PAPER_DB} --artifact ${PAPER_ARTIFACT} --market-fixture ${PAPER_MARKET_FIXTURE} --host-id ${PAPER_HOST_ID}
Restart=on-failure
RestartSec=10
WatchdogSec=60
RuntimeDirectory=trading-strategy
StateDirectory=trading-strategy
LogsDirectory=trading-strategy
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/lib/trading-strategy /var/log/trading-strategy /var/backups/trading-strategy

[Install]
WantedBy=multi-user.target
"""


ENV_TEMPLATE = """PAPER_HOST_ID=oracle-a1-paper
PAPER_DB=/var/lib/trading-strategy/memory.sqlite
PAPER_ARTIFACT=/opt/trading-strategy/artifacts/example.strategy-artifact.json
PAPER_MARKET_FIXTURE=/opt/trading-strategy/fixtures/paper-market-fixture.json
PAPER_EXPORT_DIR=/var/backups/trading-strategy
PAPER_LOG_DIR=/var/log/trading-strategy
PAPER_MAX_PER_SYMBOL_NOTIONAL=100000
PAPER_MAX_AGGREGATE_NOTIONAL=250000
PAPER_MAX_SPREAD_BPS=25
PAPER_MIN_VISIBLE_DEPTH_QTY=0
"""


LOGROTATE_TEMPLATE = """/var/log/trading-strategy/*.log {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
"""


FORBIDDEN_ENV_KEYS = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET",
    "PRIVATE_KEY",
    "WITHDRAW",
)


@dataclass(frozen=True)
class HostedPaperOpsConfig:
    repo_dir: Path = Path("/opt/trading-strategy")
    state_dir: Path = Path("/var/lib/trading-strategy")
    log_dir: Path = Path("/var/log/trading-strategy")
    backup_dir: Path = Path("/var/backups/trading-strategy")
    db_path: Path = Path("/var/lib/trading-strategy/memory.sqlite")
    template_root: Path = Path("deploy")
    min_free_mb: int = 1024


def write_hosted_paper_ops_templates(template_root: Path) -> dict[str, Path]:
    paths = {
        "systemd_unit": template_root / "systemd" / "trading-strategy-paper.service",
        "env_template": template_root / "env" / "paper-daemon.env.example",
        "logrotate": template_root / "logrotate" / "trading-strategy",
    }
    payloads = {
        "systemd_unit": SYSTEMD_UNIT,
        "env_template": ENV_TEMPLATE,
        "logrotate": LOGROTATE_TEMPLATE,
    }
    for key, path in paths.items():
        write_text_atomic(path, payloads[key])
    return paths


def build_paper_host_doctor_report(config: HostedPaperOpsConfig) -> dict[str, object]:
    directory_report = _check_directories(config)
    template_report = _check_templates(config.template_root)
    sqlite_report = _check_sqlite(config.db_path)
    disk_report = _check_disk(config.state_dir, config.min_free_mb)
    secret_report = _check_no_secret_env(config.template_root)
    checks = {
        "directories": directory_report,
        "disk": disk_report,
        "sqlite": sqlite_report,
        "templates": template_report,
        "secrets": secret_report,
    }
    status = "pass" if all(check.get("status") == "pass" for check in checks.values()) else "fail"
    return {
        "status": status,
        "mode": "paper_host_doctor",
        "requires_private_keys": False,
        "paths": {
            "repo_dir": str(config.repo_dir),
            "state_dir": str(config.state_dir),
            "log_dir": str(config.log_dir),
            "backup_dir": str(config.backup_dir),
            "db_path": str(config.db_path),
            "template_root": str(config.template_root),
        },
        **checks,
    }


def _check_directories(config: HostedPaperOpsConfig) -> dict[str, object]:
    paths = {
        "repo_dir": config.repo_dir,
        "state_dir": config.state_dir,
        "log_dir": config.log_dir,
        "backup_dir": config.backup_dir,
    }
    results: dict[str, dict[str, object]] = {}
    for key, path in paths.items():
        exists = path.exists() and path.is_dir()
        writable = _can_write(path) if exists and key != "repo_dir" else exists
        results[key] = {"path": str(path), "exists": exists, "writable": writable}
    status = "pass" if all(item["exists"] and item["writable"] for item in results.values()) else "fail"
    return {"status": status, "items": results}


def _check_templates(template_root: Path) -> dict[str, object]:
    required = {
        "trading-strategy-paper.service": template_root / "systemd" / "trading-strategy-paper.service",
        "paper-daemon.env.example": template_root / "env" / "paper-daemon.env.example",
        "trading-strategy": template_root / "logrotate" / "trading-strategy",
    }
    files: dict[str, dict[str, object]] = {}
    for name, path in required.items():
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        files[name] = {
            "path": str(path),
            "exists": path.exists(),
            "nonempty": bool(text.strip()),
            "secret_free": not _contains_forbidden_key(text),
        }
    status = "pass" if all(item["exists"] and item["nonempty"] and item["secret_free"] for item in files.values()) else "fail"
    return {"status": status, "files": files}


def _check_sqlite(db_path: Path) -> dict[str, object]:
    if not db_path.exists():
        return {"status": "fail", "exists": False, "quick_check": None, "wal_checkpoint": None}
    initialize_memory_db(db_path)
    connection = connect_sqlite(db_path)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        wal_checkpoint = connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    finally:
        connection.close()
    status = "pass" if quick_check == "ok" else "fail"
    return {
        "status": status,
        "exists": True,
        "quick_check": str(quick_check),
        "wal_checkpoint": list(wal_checkpoint) if wal_checkpoint else None,
    }


def _check_disk(path: Path, min_free_mb: int) -> dict[str, object]:
    path_exists = path.exists()
    target = path if path_exists else _nearest_existing_parent(path)
    if target is None:
        return {
            "status": "fail",
            "free_mb": 0,
            "min_free_mb": int(min_free_mb),
            "path": str(path),
            "error": "no_existing_parent",
        }
    usage = shutil.disk_usage(target)
    free_mb = int(usage.free / (1024 * 1024))
    return {
        "status": "pass" if path_exists and free_mb >= min_free_mb else "fail",
        "free_mb": free_mb,
        "min_free_mb": int(min_free_mb),
        "path": str(target),
        "target_exists": path_exists,
    }


def _check_no_secret_env(template_root: Path) -> dict[str, object]:
    env_path = template_root / "env" / "paper-daemon.env.example"
    if not env_path.exists():
        return {"status": "fail", "path": str(env_path), "forbidden_keys": []}
    text = env_path.read_text(encoding="utf-8")
    found = [key for key in FORBIDDEN_ENV_KEYS if key in text]
    return {"status": "pass" if not found else "fail", "path": str(env_path), "forbidden_keys": found}


def _contains_forbidden_key(text: str) -> bool:
    return any(key in text for key in FORBIDDEN_ENV_KEYS)


def _can_write(path: Path) -> bool:
    probe = path / ".paper_host_doctor_probe"
    try:
        write_text_atomic(probe, json.dumps({"probe": True}))
        probe.unlink()
        return True
    except OSError:
        return False


def _nearest_existing_parent(path: Path) -> Path | None:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return current
