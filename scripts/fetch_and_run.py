"""Overnight data fetch + research loop helper.

Usage (Windows Task Scheduler or manual)
-----------------------------------------
    python scripts/fetch_and_run.py --symbol BTC/USD --budget 100
    python scripts/fetch_and_run.py --symbol ETH/USD --lookback-days 180 --budget 50
    python scripts/fetch_and_run.py --symbol BTC/USD --skip-binance --budget 30

What it does
------------
1. Fetches a fresh Binance perps snapshot plus optional Alpaca spot reference
2. Validates the snapshot (gap check, sanity check)
3. Writes the study config JSON
4. Launches the engine agent loop
5. Prints a summary on exit
"""
from __future__ import annotations

import argparse
import json
import site
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Suppress annoying dependency version warnings and cp950 encoding crashes on Windows
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
VENDOR_ROOT = REPO_ROOT / ".vendor"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(VENDOR_ROOT) not in sys.path:
    sys.path.append(str(VENDOR_ROOT))
USER_SITE = site.getusersitepackages()
if isinstance(USER_SITE, str) and USER_SITE and USER_SITE not in sys.path:
    sys.path.append(USER_SITE)

from engine.app.examples import write_example_study_config
from engine.data.fetch import fetch_snapshot, load_fetched_snapshot
from engine.data.validate import validate_snapshot_bundle


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch market data and run agent loop.")
    parser.add_argument("--symbol", type=str, required=True, help="Alpaca crypto symbol (e.g., BTC/USD).")
    parser.add_argument("--binance-symbol", type=str, default="", help="Binance symbol (e.g., BTCUSDT). Derived automatically if empty.")
    parser.add_argument("--timeframe", type=str, default="1Hour", help="Candle timeframe (1Hour, 1Day, etc.).")
    parser.add_argument("--lookback-days", type=int, default=365, help="Days of history to fetch.")
    parser.add_argument("--budget", type=int, default=10, help="Agent loop execution budget.")
    parser.add_argument(
        "--skip-spot-reference",
        action="store_true",
        help="Skip optional Alpaca spot reference fetch.",
    )
    parser.add_argument(
        "--parameter-search-mode",
        type=str,
        default="optuna",
        choices=("grid", "optuna"),
        help="Planner mode written into the generated study config.",
    )
    parser.add_argument(
        "--optuna-trials",
        type=int,
        default=16,
        help="Optuna trial budget when --parameter-search-mode=optuna.",
    )
    parser.add_argument("--output-dir", type=str, default="outputs", help="Root directory for outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch data and write config, but do not execute loop.")
    return parser

def _derive_binance_symbol(alpaca_sym: str) -> str:
    """Derive BTCUSDT from BTC/USD."""
    base = alpaca_sym.split("/")[0].upper()
    return f"{base}USDT"


def _validate_snapshot(snapshot_dir: Path) -> list[str]:
    warnings_list: list[str] = []
    required_files = [
        snapshot_dir / "candles.csv",
        snapshot_dir / "funding_rates.csv",
        snapshot_dir / "open_interest.csv",
        snapshot_dir / "liquidation_notional.csv",
    ]
    for path in required_files:
        if not path.exists():
            warnings_list.append(f"missing snapshot artifact: {path.name}")
    return warnings_list


def _write_study_config(
    snapshot_dir: Path,
    output_root: Path,
    run_id: str,
    symbol: str,
    timeframe: str,
    parameter_search_mode: str,
    optuna_trials: int,
) -> Path:
    snapshot = load_fetched_snapshot(
        snapshot_dir=snapshot_dir,
        snapshot_id=f"snap-{run_id}",
        symbol=symbol,
        venue="binance",
        timeframe=timeframe,
        maker_fee_bps=2.0,
        taker_fee_bps=6.0,
    )
    config_path = snapshot_dir / "study.json"
    write_example_study_config(config_path, snapshot, run_id=run_id, seed=7)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    runtime = payload.setdefault("runtime", {})
    runtime["parameter_search_mode"] = parameter_search_mode
    runtime["optuna_trials"] = max(1, int(optuna_trials))
    research_lineage = payload.setdefault("research_lineage", {})
    research_lineage["memory_db_path"] = str(output_root / "research-memory.sqlite")
    config_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return config_path


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    symbol_alpaca = args.symbol
    symbol_binance = args.binance_symbol or _derive_binance_symbol(symbol_alpaca)
    
    today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    tf = args.timeframe
    run_id = f"{symbol_alpaca.replace('/', '')}-{tf}-{today}"
    output_root = Path(args.output_dir)
    snapshot_dir = output_root / "snapshots" / run_id
    runs_dir = output_root / "runs" / run_id
    
    print("=" * 60)
    print(f"  Fetch & Run - {symbol_alpaca} | {tf}")
    print(f"  Lookback : {args.lookback_days} days")
    print(f"  Budget   : {args.budget} iterations")
    print(f"  Output   : {snapshot_dir}")
    print("=" * 60)
    
    paths = fetch_snapshot(
        output_dir=snapshot_dir,
        symbol_alpaca=symbol_alpaca,
        symbol_binance=symbol_binance,
        timeframe=tf,
        lookback_days=args.lookback_days,
        include_spot_reference=not args.skip_spot_reference,
    )

    validation_warnings = _validate_snapshot(snapshot_dir)
    for warning in validation_warnings:
        print(f"[fetch] warning: {warning}")

    config_path = _write_study_config(
        snapshot_dir=snapshot_dir,
        output_root=output_root,
        run_id=run_id,
        symbol=symbol_alpaca,
        timeframe=tf,
        parameter_search_mode=args.parameter_search_mode,
        optuna_trials=args.optuna_trials,
    )

    snapshot = load_fetched_snapshot(
        snapshot_dir=snapshot_dir,
        snapshot_id=f"snap-{run_id}",
        symbol=symbol_alpaca,
        venue="binance",
        timeframe=tf,
        maker_fee_bps=2.0,
        taker_fee_bps=6.0,
    )
    validation_report = validate_snapshot_bundle(
        candle_timestamps=[candle.timestamp.isoformat() for candle in snapshot.candles],
        candle_opens=[candle.open for candle in snapshot.candles],
        candle_highs=[candle.high for candle in snapshot.candles],
        candle_lows=[candle.low for candle in snapshot.candles],
        candle_closes=[candle.close for candle in snapshot.candles],
        candle_volumes=[candle.volume for candle in snapshot.candles],
        funding_rates=snapshot.funding_rates,
        open_interest=snapshot.open_interest,
        liquidation_notional=snapshot.liquidation_notional,
        timeframe=snapshot.timeframe,
    )
    for warning in validation_report["warnings"]:
        print(f"[fetch] validation warning: {warning}")
        
    print(f"\n[fetch] Study config: {config_path}")
    
    if args.dry_run:
        print("[fetch] --dry-run active. Exiting.")
        return 0

    print(f"\n[fetch] Launching agent loop (budget={args.budget})...")
    runs_dir.mkdir(parents=True, exist_ok=True)
    
    db_path = output_root / "research-memory.sqlite"
    
    cmd = [
        sys.executable, "-m", "engine.app.cli", "agent-loop",
        "--config", str(config_path),
        "--output-dir", str(runs_dir),
        "--db", str(db_path),
        "--run-budget", str(args.budget)
    ]
    
    print("\n" + "=" * 60)
    try:
        subprocess.run(cmd, check=True)
        print("  - Agent loop completed successfully.")
        print(f"  Results: {runs_dir}")
    except subprocess.CalledProcessError as err:
        print(f"  X Agent loop exited with code {err.returncode}.")
        return err.returncode
    print("=" * 60)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
