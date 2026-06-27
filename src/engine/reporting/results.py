from __future__ import annotations

import csv
from pathlib import Path


V3_RESULTS_TSV_COLUMNS = [
    "experiment_id",
    "ts_start_utc",
    "ts_end_utc",
    "code_sha",
    "artifact_parent_id",
    "dataset_snapshot_id",
    "venue",
    "symbols",
    "signal_tf",
    "execution_tf",
    "family",
    "variant_id",
    "status",
    "fail_code",
    "net_return",
    "net_pnl_quote",
    "sharpe",
    "calmar",
    "max_dd",
    "turnover",
    "capacity_usd",
    "dsr",
    "pbo",
    "spa_pvalue",
    "holdout_pass",
    "description",
]


def append_results_tsv_row(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=V3_RESULTS_TSV_COLUMNS,
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        if write_header:
            writer.writeheader()
        writer.writerow({column: _format_cell(row.get(column, "")) for column in V3_RESULTS_TSV_COLUMNS})


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
