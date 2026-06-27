import copy
import glob
import json
import math
import os
import sqlite3
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


def _safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_metric(payload, *paths):
    for path in paths:
        current = payload
        found = True
        for key in path:
            if not isinstance(current, dict) or key not in current:
                found = False
                break
            current = current[key]
        if found:
            return current
    return None


def _parse_runtime_settings(payload):
    runtime_settings = payload.get("runtime_settings")
    if isinstance(runtime_settings, dict):
        return runtime_settings
    encoded = _first_metric(payload, ("artifacts", "runtime_settings_json"))
    if isinstance(encoded, str):
        try:
            decoded = json.loads(encoded)
            if isinstance(decoded, dict):
                return decoded
        except json.JSONDecodeError:
            return {}
    return {}


def _build_context(payload):
    artifacts = payload.get("artifacts", {})
    timeseries = payload.get("timeseries") or []
    symbol = artifacts.get("symbol") or payload.get("symbol") or "UNKNOWN"
    venue = artifacts.get("venue") or payload.get("venue") or "UNKNOWN"
    snapshot_id = artifacts.get("snapshot_id") or payload.get("run_id") or "latest-run"
    timeframe = (
        artifacts.get("timeframe")
        or payload.get("timeframe")
        or payload.get("snapshot", {}).get("timeframe")
        or "--"
    )
    if timeseries and len(timeseries) >= 2:
        start_value = timeseries[0].get("timestamp") or "--"
        end_value = timeseries[-1].get("timestamp") or "--"
        date_range = f"{start_value} - {end_value}"
    else:
        date_range = "--"
    return {
        "symbol": symbol,
        "venue": str(venue).upper(),
        "snapshot_id": snapshot_id,
        "date_range": date_range,
        "timeframe": timeframe,
    }


def _derive_table_stats(payload):
    if isinstance(payload.get("table_stats"), dict):
        return payload["table_stats"]
    return {}


def _derive_ranked_parameter_sets(payload):
    phases = payload.get("phases") or []
    ranked = []
    for phase in phases:
        summaries = phase.get("search_summary") or []
        selected = phase.get("selected_parameters") or {}
        if summaries:
            for summary in summaries:
                parameters = summary.get("parameters") or selected
                metric = _safe_float(summary.get("bootstrap_worst_drawdown"), None)
                if metric is None:
                    metric = abs(_safe_float(summary.get("oos_sharpe"), 0.0))
                ranked.append(
                    {
                        "label": phase.get("layer_name") or phase.get("phase_name") or "layer",
                        "metric_name": "max_drawdown",
                        "metric_value": round(abs(metric) * 100.0, 2),
                        "max_drawdown": abs(_safe_float(summary.get("bootstrap_worst_drawdown"), 0.0)),
                        "oos_net_pnl": _safe_float(summary.get("oos_net_pnl"), 0.0),
                        "oos_sharpe": _safe_float(summary.get("oos_sharpe"), 0.0),
                        "parameters": parameters,
                    }
                )
        else:
            score = _safe_float(phase.get("oos_sharpe"), 0.0)
            ranked.append(
                {
                    "label": phase.get("layer_name") or phase.get("phase_name") or "layer",
                    "metric_name": "oos_sharpe",
                    "metric_value": round(score, 2),
                    "max_drawdown": abs(_safe_float(phase.get("bootstrap_worst_drawdown"), 0.0)),
                    "oos_net_pnl": _safe_float(phase.get("oos_net_pnl"), 0.0),
                    "oos_sharpe": score,
                    "parameters": selected,
                }
            )

    if ranked:
        return ranked[:12]

    metrics = payload.get("metrics", {})
    raw_drawdown = _safe_float(
        _first_metric(payload, ("metrics", "selection_oos_drawdown"), ("metrics", "max_drawdown")),
        None,
    )
    fallback_drawdown = abs(raw_drawdown) if raw_drawdown is not None else None
    fallback_profit = _safe_float(_first_metric(payload, ("metrics", "selection_oos_net_pnl"), ("metrics", "net_profit")), None)
    fallback_sharpe = _safe_float(_first_metric(payload, ("metrics", "selection_oos_sharpe"), ("metrics", "sharpe_ratio")), None)
    if fallback_drawdown is None and fallback_profit is None and fallback_sharpe is None:
        return []
    return [
        {
            "label": payload.get("run_id", "strategy"),
            "metric_name": "max_drawdown" if fallback_drawdown is not None else "oos_sharpe",
            "metric_value": round(fallback_drawdown * 100.0, 2) if fallback_drawdown is not None else round(fallback_sharpe or 0.0, 2),
            "max_drawdown": fallback_drawdown,
            "oos_net_pnl": fallback_profit,
            "oos_sharpe": fallback_sharpe,
            "parameters": {},
        }
    ]


def _derive_analysis_modes(payload):
    modes = ["Normal Training"]
    if isinstance(payload.get("bootstrap"), dict) and payload.get("bootstrap"):
        modes.append("Bootstrap Review")
    if isinstance(payload.get("scenarios"), list) and payload.get("scenarios"):
        modes.append("Scenario Matrix")
    has_strategy_profile = bool(payload.get("runtime_settings")) or bool(payload.get("selected_parameters")) or bool(payload.get("strategy"))
    if has_strategy_profile:
        modes.append("Strategy Profile")
    return modes


def _derive_sort_metrics(payload):
    ranked_sets = _derive_ranked_parameter_sets(payload)
    sort_metrics = []
    if any(_safe_float(item.get("max_drawdown"), None) is not None for item in ranked_sets):
        sort_metrics.append("Max Drawdown")
    if any(_safe_float(item.get("oos_sharpe"), None) is not None for item in ranked_sets):
        sort_metrics.append("Sharpe Ratio")
    if any(_safe_float(item.get("oos_net_pnl"), None) is not None for item in ranked_sets):
        sort_metrics.append("Net Profit")
    return sort_metrics or ["Max Drawdown"]


def _derive_simulation_results(payload):
    metrics = payload.get("metrics") or {}
    bootstrap = payload.get("bootstrap") or {}
    results = []
    if any(key in metrics for key in ("selection_oos_net_pnl", "net_profit", "selection_oos_drawdown", "max_drawdown", "selection_oos_sharpe", "sharpe_ratio")):
        results.append("Selection")
    if any(key in bootstrap for key in ("median_net_profit", "median_max_drawdown", "median_sharpe", "median_sortino")):
        results.append("Median")
    if any(key in bootstrap for key in ("worst_case_net_profit", "worst_case_drawdown", "worst_case_sharpe", "worst_case_sortino")):
        results.append("Worst Case")
    return results or ["Selection"]


def _derive_visuals(payload):
    visuals = dict(payload.get("visuals") or {})
    visuals["context"] = _build_context(payload)
    visuals["timeseries"] = payload.get("timeseries") or []
    visuals["table_stats"] = _derive_table_stats(payload)
    visuals["ranked_parameter_sets"] = _derive_ranked_parameter_sets(payload)
    visuals["analysis_modes"] = _derive_analysis_modes(payload)
    visuals["sort_metrics"] = _derive_sort_metrics(payload)
    visuals["simulation_results"] = _derive_simulation_results(payload)
    return visuals


def normalize_dashboard_payload(payload):
    normalized = copy.deepcopy(payload)
    normalized["runtime_settings"] = _parse_runtime_settings(normalized)
    normalized["table_stats"] = _derive_table_stats(normalized)
    normalized["visuals"] = _derive_visuals(normalized)
    if "timeseries" not in normalized or not normalized["timeseries"]:
        normalized["timeseries"] = normalized["visuals"]["timeseries"]
    return normalized


def _is_demo_dashboard_path(path):
    parts = {part.lower() for part in Path(path).parts}
    name = Path(path).name.lower()
    return "fake_data" in parts or "example_run" in parts or name.startswith("fake_")


def _is_demo_dashboard_payload(payload):
    run_id = str(payload.get("run_id") or "").lower()
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    snapshot_id = str(artifacts.get("snapshot_id") or payload.get("snapshot_id") or "").lower()
    markers = (run_id, snapshot_id)
    return any(
        marker.startswith("fake")
        or marker.startswith("mock")
        or marker.startswith("example-")
        or marker.startswith("example_")
        or marker.startswith("example/")
        for marker in markers
    )


def list_dashboard_artifacts(root="outputs"):
    dashboard_files = glob.glob(os.path.join(root, "**", "*.dashboard.json"), recursive=True)
    artifacts = []

    for path in dashboard_files:
        if _is_demo_dashboard_path(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if _is_demo_dashboard_payload(payload):
            continue

        artifacts.append(
            {
                "run_id": payload.get("run_id") or payload.get("artifacts", {}).get("snapshot_id") or Path(path).stem,
                "symbol": payload.get("artifacts", {}).get("symbol") or payload.get("symbol") or "UNKNOWN",
                "status": payload.get("artifacts", {}).get("final_status") or payload.get("decision") or "unknown",
                "path": path,
                "mtime": os.path.getmtime(path),
            }
        )

    artifacts.sort(key=lambda item: item["mtime"], reverse=True)
    return artifacts


def load_latest_promoted_dashboard(root="outputs"):
    promoted = []
    dashboard_files = list_dashboard_artifacts(root=root)

    for item in dashboard_files:
        if item["status"] != "promoted":
            continue
        path = item["path"]
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        promoted.append((item["mtime"], path, payload))

    if not promoted:
        return None

    promoted.sort(key=lambda item: item[0], reverse=True)
    _, path, payload = promoted[0]
    normalized = normalize_dashboard_payload(payload)
    normalized.setdefault("visuals", {})
    normalized["visuals"]["source_path"] = path
    return normalized


def load_latest_dashboard(root="outputs"):
    dashboard_files = list_dashboard_artifacts(root=root)
    if not dashboard_files:
        return None

    path = dashboard_files[0]["path"]
    normalized = load_dashboard_file(path, restrict_to_dir=root)
    if normalized is None:
        return None
    normalized.setdefault("visuals", {})
    normalized["visuals"]["source_path"] = path
    return normalized


def load_dashboard_file(path, restrict_to_dir="outputs"):
    try:
        base_dir = Path(restrict_to_dir).resolve()
        requested_path = Path(path).resolve()
        requested_path.relative_to(base_dir)
        if _is_demo_dashboard_path(requested_path):
            return None

        with open(requested_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if _is_demo_dashboard_payload(payload):
        return None

    normalized = normalize_dashboard_payload(payload)
    normalized.setdefault("visuals", {})
    normalized["visuals"]["source_path"] = path
    return normalized


def load_test_dashboard(root="outputs"):
    test_path = Path(root) / "example_run" / "example-study.dashboard.json"
    if test_path.exists():
        try:
            with open(test_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {}

    if not payload:
        payload = {
            "run_id": "test-backtest",
            "decision": "test",
            "artifacts": {"final_status": "test", "symbol": "TESTUSDT", "venue": "TEST", "snapshot_id": "test-backtest"},
            "metrics": {
                "selection_oos_net_pnl": 12.5,
                "selection_oos_drawdown": -0.025,
                "selection_oos_sharpe": 0.42,
                "sortino_ratio": 0.6,
                "total_trades": 8,
                "win_rate": 0.625,
            },
            "bootstrap": {"pass_rate": 0.75, "median_max_drawdown": -0.03, "median_net_profit": 8.0},
            "strategy": {"backbone": "test_backtest", "layers": ["fixture"]},
            "timeseries": [
                {"timestamp": f"test-{index:02d}", "equity": equity, "drawdown": drawdown}
                for index, (equity, drawdown) in enumerate(((0, 0), (2, 0), (1, -0.5), (5, 0), (4, -0.2), (9, 0)), start=1)
            ],
        }

    normalized = normalize_dashboard_payload(payload)
    normalized["run_id"] = normalized.get("run_id") or "test-backtest"
    normalized.setdefault("visuals", {})
    normalized["visuals"]["source_mode"] = "test_backtest"
    normalized["visuals"]["source_path"] = str(test_path)
    normalized["visuals"]["is_test_data"] = True
    return normalized


def _connect_sqlite_read_only(path):
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)


def _sqlite_has_table(connection, table):
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _paper_db_candidates(root="outputs"):
    patterns = ("*.sqlite", "*.sqlite3", "*.db")
    candidates = []
    for pattern in patterns:
        candidates.extend(Path(root).glob(f"**/{pattern}"))
    candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    return candidates


def _paper_db_summary(path):
    try:
        connection = _connect_sqlite_read_only(path)
        connection.row_factory = sqlite3.Row
        if not _sqlite_has_table(connection, "order_telemetry"):
            return None
        order_count = connection.execute("SELECT COUNT(*) FROM order_telemetry").fetchone()[0]
        if order_count <= 0:
            return None
        symbol_row = connection.execute(
            "SELECT symbol FROM order_telemetry WHERE symbol IS NOT NULL AND symbol != '' LIMIT 1"
        ).fetchone()
        latest_ts = None
        for column in ("ts_last_fill", "ts_ack", "ts_send", "ts_signal"):
            try:
                row = connection.execute(
                    f"SELECT MAX({column}) AS ts FROM order_telemetry WHERE {column} IS NOT NULL AND {column} != ''"
                ).fetchone()
            except sqlite3.Error:
                row = None
            if row and row["ts"]:
                latest_ts = row["ts"]
                break
        return {
            "run_id": f"paper:{Path(path).stem}",
            "symbol": symbol_row["symbol"] if symbol_row and symbol_row["symbol"] else "PAPER",
            "status": "paper",
            "path": str(path),
            "mtime": os.path.getmtime(path),
            "latest_ts": latest_ts,
            "order_count": order_count,
        }
    except (OSError, sqlite3.Error):
        return None
    finally:
        try:
            connection.close()
        except Exception:
            pass


def list_paper_artifacts(root="outputs"):
    artifacts = []
    for path in _paper_db_candidates(root=root):
        summary = _paper_db_summary(path)
        if summary:
            artifacts.append(summary)
    artifacts.sort(key=lambda item: item["mtime"], reverse=True)
    return artifacts


def load_paper_dashboard_file(path, restrict_to_dir="outputs"):
    try:
        base_dir = Path(restrict_to_dir).resolve()
        requested_path = Path(path).resolve()
        requested_path.relative_to(base_dir)
        connection = _connect_sqlite_read_only(requested_path)
        connection.row_factory = sqlite3.Row
        if not _sqlite_has_table(connection, "order_telemetry"):
            return None
        rows = connection.execute(
            """
            SELECT *
            FROM order_telemetry
            ORDER BY COALESCE(ts_last_fill, ts_ack, ts_send, ts_signal, telemetry_id)
            """
        ).fetchall()
        if not rows:
            return None
        funding_fee = 0.0
        if _sqlite_has_table(connection, "funding_events"):
            funding_fee = connection.execute("SELECT COALESCE(SUM(funding_fee), 0.0) FROM funding_events").fetchone()[0] or 0.0
        pnl_summary = None
        if _sqlite_has_table(connection, "pnl_attribution"):
            pnl_summary = connection.execute(
                """
                SELECT
                    COALESCE(SUM(realized_strategy_pnl), 0.0),
                    COALESCE(SUM(unrealized_pnl), 0.0),
                    COALESCE(SUM(fees), 0.0),
                    COALESCE(SUM(funding), 0.0),
                    COALESCE(SUM(slippage), 0.0)
                FROM pnl_attribution
                """
            ).fetchone()
        equity_rows = []
        if _sqlite_has_table(connection, "equity_snapshots"):
            equity_rows = connection.execute(
                "SELECT ts_utc, equity FROM equity_snapshots ORDER BY ts_utc"
            ).fetchall()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        try:
            connection.close()
        except Exception:
            pass

    def value(row, key, default=None):
        return row[key] if key in row.keys() else default

    qty_filled = sum(_safe_float(value(row, "qty_filled"), 0.0) for row in rows)
    qty_submitted = sum(_safe_float(value(row, "qty_submitted"), 0.0) for row in rows)
    fee_quote = sum(_safe_float(value(row, "fee_quote"), 0.0) for row in rows)
    rejects = sum(1 for row in rows if _safe_float(value(row, "was_rejected"), 0.0))
    risk_blocks = sum(1 for row in rows if _safe_float(value(row, "risk_blocked"), 0.0))
    slip_values = [_safe_float(value(row, "slip_bps"), None) for row in rows]
    slip_values = [item for item in slip_values if item is not None]
    maker_values = [_safe_float(value(row, "maker_ratio"), None) for row in rows]
    maker_values = [item for item in maker_values if item is not None]
    symbols = [value(row, "symbol") for row in rows if value(row, "symbol")]
    symbol = symbols[0] if symbols else "PAPER"
    avg_slip = sum(slip_values) / len(slip_values) if slip_values else 0.0
    avg_maker = sum(maker_values) / len(maker_values) if maker_values else None
    fill_rate = qty_filled / qty_submitted if qty_submitted else 0.0
    filled_trade_count = sum(1 for row in rows if _safe_float(value(row, "qty_filled"), 0.0) > 0.0)

    realized_pnl = _safe_float(pnl_summary[0], 0.0) if pnl_summary else 0.0
    unrealized_pnl = _safe_float(pnl_summary[1], 0.0) if pnl_summary else 0.0
    attributed_fees = _safe_float(pnl_summary[2], fee_quote) if pnl_summary else fee_quote
    attributed_funding = _safe_float(pnl_summary[3], funding_fee) if pnl_summary else funding_fee
    attributed_slippage = _safe_float(pnl_summary[4], 0.0) if pnl_summary else 0.0
    net_pnl = realized_pnl + unrealized_pnl - attributed_fees - attributed_funding - attributed_slippage

    timeseries = []
    peak = None
    for ts, raw_equity in equity_rows:
        equity = _safe_float(raw_equity, None)
        if equity is None:
            continue
        peak = equity if peak is None else max(peak, equity)
        drawdown = 0.0 if not peak else min(0.0, (equity - peak) / abs(peak))
        timeseries.append({"timestamp": ts, "equity": round(equity, 8), "drawdown": drawdown})
    if not timeseries:
        cumulative_cost = 0.0
        peak = 0.0
        for index, row in enumerate(rows, start=1):
            cumulative_cost += _safe_float(value(row, "fee_quote"), 0.0)
            equity = -cumulative_cost
            peak = max(peak, equity)
            drawdown = 0.0 if peak == 0.0 else min(0.0, (equity - peak) / max(abs(peak), 1.0))
            ts = value(row, "ts_last_fill") or value(row, "ts_ack") or value(row, "ts_send") or value(row, "ts_signal") or f"paper-{index}"
            timeseries.append({"timestamp": ts, "equity": round(equity, 8), "drawdown": drawdown})

    payload = {
        "run_id": f"paper:{Path(path).stem}",
        "decision": "paper",
        "artifacts": {"final_status": "paper", "symbol": symbol, "venue": "PAPER", "snapshot_id": f"paper:{Path(path).stem}"},
        "metrics": {
            "selection_oos_net_pnl": net_pnl,
            "selection_oos_drawdown": min((item["drawdown"] for item in timeseries), default=0.0),
            "selection_oos_sharpe": 0.0,
            "sortino_ratio": 0.0,
            "total_trades": filled_trade_count,
            "win_rate": None,
            "paper_fill_rate": fill_rate,
            "paper_avg_slip_bps": avg_slip,
            "paper_rejects": rejects,
            "paper_risk_blocks": risk_blocks,
        },
        "bootstrap": {"pass_rate": None, "median_max_drawdown": min((item["drawdown"] for item in timeseries), default=0.0)},
        "runtime_settings": {
            "source": "paper telemetry",
            "orders": len(rows),
            "filled_trades": filled_trade_count,
            "fill_rate": round(fill_rate, 6),
            "realized_pnl": round(realized_pnl, 8),
            "unrealized_pnl": round(unrealized_pnl, 8),
            "qty_submitted": round(qty_submitted, 8),
            "qty_filled": round(qty_filled, 8),
            "avg_slip_bps": round(avg_slip, 6),
            "maker_ratio": round(avg_maker, 6) if avg_maker is not None else "--",
            "funding_fee": round(funding_fee, 8),
            "risk_blocks": risk_blocks,
            "rejects": rejects,
        },
        "strategy": {"backbone": "paper_executor", "layers": ["real_telemetry"]},
        "timeseries": timeseries,
        "table_stats": {"all_commission": fee_quote},
    }
    normalized = normalize_dashboard_payload(payload)
    normalized.setdefault("visuals", {})
    normalized["visuals"]["source_mode"] = "paper_trading"
    normalized["visuals"]["source_path"] = str(path)
    return normalized


def load_latest_paper_dashboard(root="outputs"):
    artifacts = list_paper_artifacts(root=root)
    if not artifacts:
        return None
    return load_paper_dashboard_file(artifacts[0]["path"], restrict_to_dir=root)


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


class DashboardHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self.path = "/dashboard.html"
            return SimpleHTTPRequestHandler.do_GET(self)

        if parsed.path == "/api/test_dashboard":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_test_dashboard()).encode("utf-8"))
            return

        if parsed.path == "/api/latest_dashboard":
            query = parse_qs(parsed.query)
            source = query.get("source", ["strategy"])[0]
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            latest_payload = load_latest_paper_dashboard() if source == "paper" else load_latest_dashboard()
            if latest_payload is None:
                message = (
                    "No paper trading telemetry found yet. Run paper execution first; this mode never uses test data."
                    if source == "paper"
                    else "No real strategy dashboard artifacts found yet. Use Test Backtest mode or generate a real run dashboard first."
                )
                latest_payload = {
                    "error": message,
                    "visuals": {
                        "analysis_modes": [],
                        "sort_metrics": [],
                        "simulation_results": [],
                    },
                }
            self.wfile.write(json.dumps(latest_payload).encode("utf-8"))
            return

        if parsed.path == "/api/dashboard_files":
            query = parse_qs(parsed.query)
            source = query.get("source", ["strategy"])[0]
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            items = list_paper_artifacts() if source == "paper" else list_dashboard_artifacts()
            self.wfile.write(json.dumps({"items": items}).encode("utf-8"))
            return

        if parsed.path == "/api/dashboard_file":
            query = parse_qs(parsed.query)
            requested_path = query.get("path", [None])[0]
            source = query.get("source", ["strategy"])[0]
            if source == "paper":
                payload = load_paper_dashboard_file(requested_path) if requested_path else None
            else:
                payload = load_dashboard_file(requested_path) if requested_path else None
            self.send_response(200 if payload else 404)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload or {"error": "Dashboard file not found"}).encode("utf-8"))
            return

        decoded_path = unquote(parsed.path)
        allowed_static = {"/dashboard.html", "/dashboard.js"}
        if decoded_path in allowed_static:
            return SimpleHTTPRequestHandler.do_GET(self)
        if decoded_path.startswith("/assets/") and ".." not in Path(decoded_path).parts:
            asset_root = (Path.cwd() / "assets").resolve()
            requested_asset = (Path.cwd() / decoded_path.lstrip("/")).resolve()
            try:
                requested_asset.relative_to(asset_root)
            except ValueError:
                pass
            else:
                return SimpleHTTPRequestHandler.do_GET(self)
        self.send_error(404, "Not found")


if __name__ == "__main__":
    port = 8080
    print("==================================================")
    print("ProofAlpha Dashboard Server Running")
    print(f"Local URL: http://localhost:{port}")
    print("Watching 'outputs/' for strategy and paper evidence artifacts")
    print("==================================================")
    server = ReusableHTTPServer(("localhost", port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()
