from __future__ import annotations

import json
from pathlib import Path


def load_campaign_manifest_payload(manifest_path: Path) -> dict[str, object]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_campaign_report_payload(report_path: Path) -> dict[str, object]:
    return json.loads(report_path.read_text(encoding="utf-8"))


def resolve_campaign_path(manifest_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (manifest_path.parent / candidate).resolve()


def expand_campaign_manifest(
    manifest_path: Path,
    output_report_path: Path,
) -> dict[str, object]:
    manifest = load_campaign_manifest_payload(manifest_path)
    campaign_id = str(manifest.get("campaign_id", output_report_path.stem))
    entries = manifest.get("entries", [])
    if not isinstance(entries, list) or not entries:
        raise SystemExit("campaign manifest must include a non-empty entries list")

    manifest_vars = manifest.get("vars", {})
    if manifest_vars is None:
        manifest_vars = {}
    if not isinstance(manifest_vars, dict):
        raise SystemExit("campaign manifest vars must be an object")

    defaults = _build_campaign_defaults(manifest)
    campaign_template_values = {
        "campaign_id": campaign_id,
        **{str(key): value for key, value in manifest_vars.items()},
    }

    expanded_entries: list[dict[str, object]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"campaign entry {index} must be an object")
        expanded_entries.extend(
            _expand_campaign_entry(
                manifest_path=manifest_path,
                output_report_path=output_report_path,
                index=index,
                entry=entry,
                defaults=defaults,
                campaign_template_values=campaign_template_values,
            )
        )

    return {
        "campaign_id": campaign_id,
        "continue_on_error": bool(manifest.get("continue_on_error", True)),
        "defaults": defaults,
        "entries": expanded_entries,
        "manifest_path": str(manifest_path),
        "report_path": str(output_report_path),
        "vars": campaign_template_values,
    }


def build_retry_campaign_manifest(
    campaign_report_path: Path,
    output_report_path: Path,
    *,
    entry_status: str,
) -> dict[str, object]:
    report_payload = load_campaign_report_payload(campaign_report_path)
    campaign_id = str(report_payload.get("campaign_id", output_report_path.stem))
    entries = report_payload.get("entries", [])
    if not isinstance(entries, list):
        raise SystemExit("campaign report entries must be a list")

    selected_entries: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not _matches_retry_status(str(entry.get("status", "unknown")), entry_status):
            continue
        selected_entries.append(_build_retry_entry(entry, campaign_report_path=campaign_report_path))

    if not selected_entries:
        raise SystemExit(f"campaign report does not include any entries matching retry status '{entry_status}'")

    return {
        "campaign_id": f"{campaign_id}-retry-{entry_status}",
        "continue_on_error": True,
        "source_campaign_report_path": str(campaign_report_path),
        "entry_status": entry_status,
        "entries": selected_entries,
    }


def _build_campaign_defaults(manifest: dict[str, object]) -> dict[str, object]:
    defaults: dict[str, object] = {}
    for key in ("command", "db", "memory_dir", "memory_limit", "memory_quality_policy", "strict_quality", "output_dir"):
        if key in manifest:
            defaults[key] = manifest[key]

    explicit_defaults = manifest.get("defaults", {})
    if explicit_defaults is None:
        explicit_defaults = {}
    if not isinstance(explicit_defaults, dict):
        raise SystemExit("campaign manifest defaults must be an object")
    defaults.update({str(key): value for key, value in explicit_defaults.items()})
    return defaults


def _expand_campaign_entry(
    *,
    manifest_path: Path,
    output_report_path: Path,
    index: int,
    entry: dict[str, object],
    defaults: dict[str, object],
    campaign_template_values: dict[str, object],
) -> list[dict[str, object]]:
    entry_vars = entry.get("vars", {})
    if entry_vars is None:
        entry_vars = {}
    if not isinstance(entry_vars, dict):
        raise SystemExit(f"campaign entry {index} vars must be an object")

    matrix = entry.get("matrix")
    if matrix is None:
        matrix_rows: list[dict[str, object]] = [{}]
    else:
        if not isinstance(matrix, list) or not matrix:
            raise SystemExit(f"campaign entry {index} matrix must be a non-empty list")
        matrix_rows = []
        for matrix_index, raw_row in enumerate(matrix, start=1):
            if not isinstance(raw_row, dict):
                raise SystemExit(f"campaign entry {index} matrix row {matrix_index} must be an object")
            matrix_rows.append({str(key): value for key, value in raw_row.items()})

    expanded: list[dict[str, object]] = []
    for matrix_index, matrix_values in enumerate(matrix_rows, start=1):
        template_values = {
            **campaign_template_values,
            **{str(key): value for key, value in entry_vars.items()},
            **matrix_values,
        }
        fallback_name = f"entry-{index}" if len(matrix_rows) == 1 else f"entry-{index}-{matrix_index}"
        name_template = entry.get("name", entry.get("name_template", fallback_name))
        name = _render_template(str(name_template), template_values)
        command = str(entry.get("command", defaults.get("command", "run")))
        config_path = resolve_campaign_path(
            manifest_path,
            _render_template(str(entry.get("config", "")), template_values),
        )

        output_dir_template = entry.get("output_dir", defaults.get("output_dir", str(output_report_path.parent / name)))
        output_dir = resolve_campaign_path(
            manifest_path,
            _render_template(str(output_dir_template), template_values),
        )

        db_path = _resolve_optional_template_path(
            manifest_path,
            entry.get("db", defaults.get("db")),
            template_values,
        )
        memory_dir = _resolve_optional_template_path(
            manifest_path,
            entry.get("memory_dir", defaults.get("memory_dir")),
            template_values,
        )
        memory_limit = int(entry.get("memory_limit", defaults.get("memory_limit", 25)))
        memory_quality_policy = str(entry.get("memory_quality_policy", defaults.get("memory_quality_policy", "clean-only")))
        strict_quality = bool(entry.get("strict_quality", defaults.get("strict_quality", False)))

        expanded.append(
            {
                "name": name,
                "command": command,
                "config_path": config_path,
                "output_dir": output_dir,
                "db_path": db_path,
                "memory_dir": memory_dir,
                "memory_limit": memory_limit,
                "memory_quality_policy": memory_quality_policy,
                "strict_quality": strict_quality,
                "template_values": template_values,
            }
        )
    return expanded


def _resolve_optional_template_path(
    manifest_path: Path,
    raw_value: object,
    template_values: dict[str, object],
) -> Path | None:
    if not isinstance(raw_value, str) or not raw_value:
        return None
    rendered = _render_template(raw_value, template_values)
    return resolve_campaign_path(manifest_path, rendered)


def _render_template(value: str, template_values: dict[str, object]) -> str:
    try:
        return value.format(**template_values)
    except KeyError as exc:
        missing_key = str(exc).strip("'")
        raise SystemExit(f"campaign template is missing value for '{missing_key}'") from exc


def _matches_retry_status(status: str, retry_status: str) -> bool:
    if retry_status == "all":
        return True
    if retry_status == "non-promoted":
        return status != "promoted"
    return status == retry_status


def _build_retry_entry(entry: dict[str, object], *, campaign_report_path: Path) -> dict[str, object]:
    output_dir_raw = entry.get("output_dir")
    output_dir = _resolve_report_entry_path(campaign_report_path, output_dir_raw)
    retry_output_dir = (
        output_dir.parent / f"{output_dir.name}-retry"
        if output_dir is not None
        else Path(f"retry-{entry.get('name', 'entry')}")
    )
    config_path = _resolve_report_entry_path(campaign_report_path, entry.get("config_path"))
    retry_entry: dict[str, object] = {
        "name": entry.get("name"),
        "command": entry.get("command"),
        "config": str(config_path) if config_path is not None else entry.get("config_path"),
        "output_dir": str(retry_output_dir),
    }
    for key in ("db_path", "memory_dir", "memory_limit", "memory_quality_policy", "strict_quality"):
        value = entry.get(key)
        if value is None:
            continue
        retry_key = "db" if key == "db_path" else key
        if key in {"db_path", "memory_dir"}:
            resolved_value = _resolve_report_entry_path(campaign_report_path, value)
            retry_entry[retry_key] = str(resolved_value) if resolved_value is not None else value
        else:
            retry_entry[retry_key] = value
    return retry_entry


def _resolve_report_entry_path(campaign_report_path: Path, raw_value: object) -> Path | None:
    if not isinstance(raw_value, str) or not raw_value:
        return None
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return candidate
    report_relative = (campaign_report_path.parent / candidate).resolve()
    if report_relative.exists():
        return report_relative
    return candidate.resolve()
