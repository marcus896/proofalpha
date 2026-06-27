from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from engine.io.artifacts import write_json_atomic


ARTIFACT_SCHEMA_VERSION = "strategy-artifact-v1"
ALLOWED_ROLLOUT_STAGES = (
    "backtest",
    "paper",
    "shadow_live",
    "tiny_live",
    "pilot_live",
    "scaled_live",
    "paused",
    "retired",
)
ACTIVE_ROLLOUT_STAGES = set(ALLOWED_ROLLOUT_STAGES) - {"paused", "retired"}

REQUIRED_ARTIFACT_FIELDS = (
    "artifact_id",
    "created_at_utc",
    "strategy_id",
    "family",
    "variant_id",
    "venue",
    "signal_timeframe",
    "execution_timeframe",
    "symbol_scope",
    "regime_scope",
    "feature_version",
    "data_snapshot_ids",
    "execution_model",
    "cost_model",
    "scenario_pack",
    "parameters",
    "risk_limits",
    "order_policy",
    "validation_report_id",
    "code_sha",
    "artifact_sha256",
    "rollout_stage",
    "promotion_approved",
    "validation_status",
)

ROLLOUT_GATE_REQUIREMENTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("backtest", "paper"): ("full_validation_pass",),
    ("paper", "shadow_live"): ("paper_stability_pass", "telemetry_complete"),
    ("shadow_live", "tiny_live"): ("paper_live_divergence_within_band",),
    ("tiny_live", "pilot_live"): ("live_risk_calibrated", "live_cost_calibrated", "no_unresolved_risk_events"),
    ("pilot_live", "scaled_live"): ("explicit_user_approval", "revalidation_pass"),
}


@dataclass(frozen=True)
class ArtifactValidation:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    artifact_sha256: str | None = None
    normalized_artifact: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RolloutTransitionDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ManifestValidation:
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaperAuthorityDecision:
    allowed: bool
    reduce_only: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PromotionManifest:
    artifact_id: str
    strategy_graph_hash: str
    data_snapshot_hash: str
    feature_contract_hash: str
    validation_bundle_hash: str
    gate_results: dict[str, bool]
    scenario_results: dict[str, bool]
    regime_results: dict[str, bool]
    capacity_result: dict[str, object]
    turnover_result: dict[str, object]
    paper_eligibility: bool
    risk_limits: dict[str, object]
    expiry_time_utc: str
    rollback_artifact_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "PromotionManifest":
        if not isinstance(payload, dict):
            raise ValueError("not_promotion_manifest")
        return cls(
            artifact_id=str(payload.get("artifact_id", "")),
            strategy_graph_hash=str(payload.get("strategy_graph_hash", "")),
            data_snapshot_hash=str(payload.get("data_snapshot_hash", "")),
            feature_contract_hash=str(payload.get("feature_contract_hash", "")),
            validation_bundle_hash=str(payload.get("validation_bundle_hash", "")),
            gate_results=_bool_dict(payload.get("gate_results")),
            scenario_results=_bool_dict(payload.get("scenario_results")),
            regime_results=_bool_dict(payload.get("regime_results")),
            capacity_result=_json_object(payload.get("capacity_result")),
            turnover_result=_json_object(payload.get("turnover_result")),
            paper_eligibility=bool(payload.get("paper_eligibility", False)),
            risk_limits=_json_object(payload.get("risk_limits")),
            expiry_time_utc=str(payload.get("expiry_time_utc", "")),
            rollback_artifact_id=(
                str(payload.get("rollback_artifact_id"))
                if payload.get("rollback_artifact_id") not in (None, "")
                else None
            ),
        )


@dataclass(frozen=True)
class RollbackManifest:
    artifact_id: str
    parent_artifact_id: str
    rollback_reason: str
    rollback_compatible: bool
    fallback_stage: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "RollbackManifest":
        if not isinstance(payload, dict):
            raise ValueError("not_rollback_manifest")
        return cls(
            artifact_id=str(payload.get("artifact_id", "")),
            parent_artifact_id=str(payload.get("parent_artifact_id", "")),
            rollback_reason=str(payload.get("rollback_reason", "")),
            rollback_compatible=bool(payload.get("rollback_compatible", False)),
            fallback_stage=str(payload.get("fallback_stage", "")),
        )


@dataclass(frozen=True)
class ArtifactCompatibilityReport:
    compatible: bool
    checks: dict[str, bool]
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_strategy_artifact(payload: dict[str, object]) -> dict[str, object]:
    artifact = _normalize_artifact_payload(payload)
    if not artifact["artifact_id"]:
        artifact["artifact_id"] = _default_artifact_id(artifact)
    if artifact.get("promotion_approved") is True and "promotion_manifest" not in artifact:
        artifact["promotion_manifest"] = build_promotion_manifest(artifact).to_dict()
    artifact["artifact_sha256"] = _artifact_hash(
        {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    )
    return artifact


def validate_strategy_artifact(payload: dict[str, object]) -> ArtifactValidation:
    if not isinstance(payload, dict) or payload.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        return ArtifactValidation(passed=False, reasons=["not_strategy_artifact"])

    reasons: list[str] = []
    missing = [field_name for field_name in REQUIRED_ARTIFACT_FIELDS if field_name not in payload]
    reasons.extend(f"missing:{field_name}" for field_name in missing)

    if payload.get("venue") != "binance_usdm":
        reasons.append("venue_not_allowed")
    if payload.get("signal_timeframe") != "1h":
        reasons.append("signal_timeframe_not_allowed")
    if payload.get("execution_timeframe") != "15m":
        reasons.append("execution_timeframe_not_allowed")
    if payload.get("execution_model") != "binance_usdm_v3":
        reasons.append("execution_model_not_allowed")
    if payload.get("rollout_stage") not in ALLOWED_ROLLOUT_STAGES:
        reasons.append("rollout_stage_not_allowed")
    if payload.get("promotion_approved") is not True:
        reasons.append("artifact_not_approved")
    if payload.get("validation_status") not in {"passed", "current"}:
        reasons.append("validation_not_current")
    if payload.get("promotion_approved") is True:
        manifest_validation = validate_promotion_manifest(payload, payload.get("promotion_manifest"))
        reasons.extend(manifest_validation.reasons)

    for field_name in ("symbol_scope", "regime_scope", "data_snapshot_ids"):
        if not isinstance(payload.get(field_name), list) or not payload.get(field_name):
            reasons.append(f"invalid:{field_name}")
    for field_name in ("parameters", "risk_limits", "order_policy"):
        if not isinstance(payload.get(field_name), dict):
            reasons.append(f"invalid:{field_name}")
    if "cost_model_config" in payload and not isinstance(payload.get("cost_model_config"), dict):
        reasons.append("invalid:cost_model_config")

    expected_hash = _artifact_hash({key: value for key, value in payload.items() if key != "artifact_sha256"})
    artifact_hash = str(payload.get("artifact_sha256", ""))
    if artifact_hash and artifact_hash != expected_hash:
        reasons.append("artifact_checksum_mismatch")

    return ArtifactValidation(
        passed=not reasons,
        reasons=sorted(set(reasons)),
        artifact_sha256=expected_hash,
        normalized_artifact={key: payload[key] for key in sorted(payload) if key != "artifact_sha256"},
    )


def write_strategy_artifact(path: Path, artifact: dict[str, object]) -> Path:
    validation = validate_strategy_artifact(artifact)
    if not validation.passed:
        raise ValueError(",".join(validation.reasons))
    return write_json_atomic(path, artifact)


def load_strategy_artifact(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("not_strategy_artifact")
    validation = validate_strategy_artifact(payload)
    if not validation.passed:
        raise ValueError(",".join(validation.reasons))
    return payload


def list_strategy_artifacts(directory: Path) -> list[dict[str, object]]:
    if not directory.exists():
        return []
    records: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.strategy-artifact.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        validation = validate_strategy_artifact(payload if isinstance(payload, dict) else {})
        records.append(
            {
                "path": str(path),
                "artifact_id": payload.get("artifact_id") if isinstance(payload, dict) else None,
                "variant_id": payload.get("variant_id") if isinstance(payload, dict) else None,
                "rollout_stage": payload.get("rollout_stage") if isinstance(payload, dict) else None,
                "passed": validation.passed,
                "reasons": validation.reasons,
            }
        )
    return records


def evaluate_rollout_transition(
    *,
    from_stage: str,
    to_stage: str,
    gate_evidence: dict[str, object],
) -> RolloutTransitionDecision:
    if from_stage not in ACTIVE_ROLLOUT_STAGES or to_stage not in ACTIVE_ROLLOUT_STAGES:
        return RolloutTransitionDecision(allowed=False, reasons=["rollout_stage_not_active"])
    required = list(ROLLOUT_GATE_REQUIREMENTS.get((from_stage, to_stage), ()))
    if not required:
        return RolloutTransitionDecision(
            allowed=False,
            reasons=["rollout_stage_skip_not_allowed"],
            required_evidence=[],
        )
    missing = [name for name in required if gate_evidence.get(name) is not True]
    return RolloutTransitionDecision(
        allowed=not missing,
        reasons=[f"missing_gate_evidence:{name}" for name in missing],
        required_evidence=required,
    )


def build_promotion_manifest(
    artifact: dict[str, object],
    *,
    expiry_time_utc: str | None = None,
) -> PromotionManifest:
    gate_details = artifact.get("validation_gate_details", [])
    gate_results = _gate_results_from_details(gate_details)
    if not gate_results:
        gate_results = _bool_dict(artifact.get("gate_results"))
    if not gate_results:
        gate_results = {"validation_status": artifact.get("validation_status") in {"passed", "current"}}
    scenario_results = _bool_dict(artifact.get("scenario_results"))
    regime_results = _bool_dict(artifact.get("regime_results"))
    capacity_result = _json_object(artifact.get("capacity_result"))
    turnover_result = _json_object(artifact.get("turnover_result"))
    return PromotionManifest(
        artifact_id=str(artifact.get("artifact_id", "")),
        strategy_graph_hash=_stable_hash(
            {
                "strategy_id": artifact.get("strategy_id", ""),
                "family": artifact.get("family", ""),
                "variant_id": artifact.get("variant_id", ""),
                "parameters": artifact.get("parameters", {}),
            }
        ),
        data_snapshot_hash=_stable_hash(artifact.get("data_snapshot_ids", [])),
        feature_contract_hash=str(artifact.get("feature_contract_hash") or _stable_hash(artifact.get("feature_version", ""))),
        validation_bundle_hash=_validation_bundle_hash(artifact),
        gate_results=gate_results,
        scenario_results=scenario_results,
        regime_results=regime_results,
        capacity_result=capacity_result,
        turnover_result=turnover_result,
        paper_eligibility=_paper_eligibility(gate_results, scenario_results, regime_results, capacity_result, turnover_result),
        risk_limits=_json_object(artifact.get("risk_limits")),
        expiry_time_utc=expiry_time_utc or str(artifact.get("expiry_time_utc") or "2099-12-31T00:00:00Z"),
        rollback_artifact_id=(
            str(artifact.get("rollback_artifact_id"))
            if artifact.get("rollback_artifact_id") not in (None, "")
            else None
        ),
    )


def validate_promotion_manifest(
    artifact: dict[str, object],
    manifest_payload: object,
    *,
    now_utc: str | None = None,
) -> ManifestValidation:
    reasons: list[str] = []
    if not isinstance(manifest_payload, dict):
        return ManifestValidation(False, ["missing_promotion_manifest"])
    try:
        manifest = PromotionManifest.from_dict(manifest_payload)
    except ValueError as exc:
        return ManifestValidation(False, [str(exc)])
    expected = build_promotion_manifest(artifact, expiry_time_utc=manifest.expiry_time_utc)
    if manifest.artifact_id != artifact.get("artifact_id"):
        reasons.append("manifest_artifact_id_mismatch")
    for field_name in (
        "strategy_graph_hash",
        "data_snapshot_hash",
        "feature_contract_hash",
        "validation_bundle_hash",
    ):
        if getattr(manifest, field_name) != getattr(expected, field_name):
            reasons.append(f"manifest_{field_name}_mismatch")
    if manifest.gate_results != expected.gate_results:
        reasons.append("manifest_gate_results_mismatch")
    if manifest.risk_limits != expected.risk_limits:
        reasons.append("manifest_risk_limits_mismatch")
    if not manifest.paper_eligibility:
        reasons.append("manifest_paper_ineligible")
    if _is_expired(manifest.expiry_time_utc, now_utc):
        reasons.append("artifact_expired")
    return ManifestValidation(not reasons, sorted(set(reasons)))


def paper_authority_decision(
    artifact: dict[str, object],
    *,
    now_utc: str | None = None,
    reduce_only: bool = False,
) -> PaperAuthorityDecision:
    validation = validate_strategy_artifact(artifact)
    if not validation.passed:
        expired_only = validation.reasons == ["artifact_expired"] or set(validation.reasons) == {"artifact_expired"}
        if expired_only and reduce_only:
            return PaperAuthorityDecision(True, True, ["artifact_expired"])
        return PaperAuthorityDecision(False, expired_only, list(validation.reasons))
    manifest = PromotionManifest.from_dict(artifact.get("promotion_manifest"))
    if _is_expired(manifest.expiry_time_utc, now_utc):
        if reduce_only:
            return PaperAuthorityDecision(True, True, ["artifact_expired"])
        return PaperAuthorityDecision(False, True, ["artifact_expired"])
    return PaperAuthorityDecision(True, False, [])


def build_rollback_manifest(
    *,
    artifact_id: str,
    parent_artifact_id: str,
    rollback_reason: str,
    rollback_compatible: bool,
    fallback_stage: str,
) -> RollbackManifest:
    return RollbackManifest(
        artifact_id=artifact_id,
        parent_artifact_id=parent_artifact_id,
        rollback_reason=rollback_reason,
        rollback_compatible=bool(rollback_compatible),
        fallback_stage=fallback_stage,
    )


def validate_rollback_manifest(payload: object) -> ManifestValidation:
    reasons: list[str] = []
    try:
        manifest = RollbackManifest.from_dict(payload)
    except ValueError as exc:
        return ManifestValidation(False, [str(exc)])
    if not manifest.artifact_id:
        reasons.append("missing_artifact_id")
    if not manifest.parent_artifact_id:
        reasons.append("missing_parent_artifact_id")
    if not manifest.rollback_reason:
        reasons.append("missing_rollback_reason")
    if manifest.fallback_stage not in ALLOWED_ROLLOUT_STAGES:
        reasons.append("invalid_fallback_stage")
    return ManifestValidation(not reasons, sorted(set(reasons)))


def build_artifact_compatibility_report(
    artifact: dict[str, object],
    *,
    expected_venue: str,
    expected_signal_timeframe: str,
    expected_execution_timeframe: str,
    expected_execution_model: str,
    allowed_symbols: set[str],
    feature_contract_hash: str,
    max_notional: float,
) -> ArtifactCompatibilityReport:
    artifact_symbols = {str(symbol) for symbol in artifact.get("symbol_scope", []) if isinstance(symbol, str)}
    risk_limits = _json_object(artifact.get("risk_limits"))
    checks = {
        "venue": artifact.get("venue") == expected_venue,
        "signal_timeframe": artifact.get("signal_timeframe") == expected_signal_timeframe,
        "execution_timeframe": artifact.get("execution_timeframe") == expected_execution_timeframe,
        "execution_model": artifact.get("execution_model") == expected_execution_model,
        "symbol_universe": bool(artifact_symbols) and artifact_symbols.issubset(set(allowed_symbols)),
        "feature_contract": str(artifact.get("feature_contract_hash", "")) == feature_contract_hash,
        "risk_limits": float(risk_limits.get("max_notional", 0.0)) <= float(max_notional),
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return ArtifactCompatibilityReport(compatible=not reasons, checks=checks, reasons=reasons)


def _normalize_artifact_payload(payload: dict[str, object]) -> dict[str, object]:
    artifact: dict[str, object] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_id": payload.get("artifact_id", ""),
        "created_at_utc": payload.get("created_at_utc", ""),
        "strategy_id": payload.get("strategy_id", ""),
        "family": payload.get("family", ""),
        "variant_id": payload.get("variant_id", ""),
        "venue": payload.get("venue", ""),
        "signal_timeframe": payload.get("signal_timeframe", ""),
        "execution_timeframe": payload.get("execution_timeframe", ""),
        "symbol_scope": sorted(_string_list(payload.get("symbol_scope"))),
        "regime_scope": sorted(_string_list(payload.get("regime_scope"))),
        "feature_version": payload.get("feature_version", ""),
        "data_snapshot_ids": sorted(_string_list(payload.get("data_snapshot_ids"))),
        "execution_model": payload.get("execution_model", ""),
        "cost_model": payload.get("cost_model", ""),
        "scenario_pack": payload.get("scenario_pack", ""),
        "parameters": _json_object(payload.get("parameters")),
        "risk_limits": _json_object(payload.get("risk_limits")),
        "order_policy": _json_object(payload.get("order_policy")),
        "validation_report_id": payload.get("validation_report_id", ""),
        "code_sha": payload.get("code_sha", ""),
        "rollout_stage": payload.get("rollout_stage", "backtest"),
        "promotion_approved": bool(payload.get("promotion_approved", False)),
        "validation_status": payload.get("validation_status", ""),
        "expiry_time_utc": payload.get("expiry_time_utc", "2099-12-31T00:00:00Z"),
    }
    if "cost_model_config" in payload:
        artifact["cost_model_config"] = _json_object(payload.get("cost_model_config"))
    if "validation_gate_details" in payload:
        gate_details = payload.get("validation_gate_details")
        artifact["validation_gate_details"] = gate_details if isinstance(gate_details, list) else []
    for field_name in (
        "feature_contract_hash",
        "scenario_results",
        "regime_results",
        "capacity_result",
        "turnover_result",
        "promotion_manifest",
        "rollback_manifest",
    ):
        if field_name in payload:
            artifact[field_name] = payload[field_name]
    return artifact


def _artifact_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _default_artifact_id(artifact: dict[str, object]) -> str:
    seed = {
        "strategy_id": artifact.get("strategy_id", ""),
        "variant_id": artifact.get("variant_id", ""),
        "validation_report_id": artifact.get("validation_report_id", ""),
        "code_sha": artifact.get("code_sha", ""),
    }
    return f"artifact-{_artifact_hash(seed)[:16]}"


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str) and item.strip()]


def _json_object(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    return {}


def _bool_dict(raw: object) -> dict[str, bool]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): bool(value) for key, value in raw.items()}


def _gate_results_from_details(raw: object) -> dict[str, bool]:
    if not isinstance(raw, list):
        return {}
    results: dict[str, bool] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            results[name] = bool(item.get("passed", False))
    return results


def _paper_eligibility(
    gate_results: dict[str, bool],
    scenario_results: dict[str, bool],
    regime_results: dict[str, bool],
    capacity_result: dict[str, object],
    turnover_result: dict[str, object],
) -> bool:
    required_gate_ok = bool(gate_results) and all(gate_results.values())
    scenario_ok = not scenario_results or all(scenario_results.values())
    regime_ok = not regime_results or all(regime_results.values())
    capacity_ok = capacity_result.get("passed", True) is True
    turnover_ok = turnover_result.get("passed", True) is True
    return required_gate_ok and scenario_ok and regime_ok and capacity_ok and turnover_ok


def _validation_bundle_hash(artifact: dict[str, object]) -> str:
    return _stable_hash(
        {
            "validation_report_id": artifact.get("validation_report_id", ""),
            "validation_status": artifact.get("validation_status", ""),
            "validation_gate_details": artifact.get("validation_gate_details", []),
        }
    )


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _is_expired(expiry_time_utc: str, now_utc: str | None = None) -> bool:
    expiry = _parse_utc(expiry_time_utc)
    if expiry is None:
        return True
    now = _parse_utc(now_utc) or datetime.now(timezone.utc)
    return now > expiry
