from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math


VALID_SIDES = {"BUY", "SELL"}
VALID_INTENT_TYPES = {"open", "increase", "reduction", "close"}
VALID_URGENCY = {"low", "normal", "urgent"}


@dataclass(frozen=True)
class InternalOrderIntent:
    intent_id: str
    artifact_id: str
    portfolio_plan_id: str
    symbol: str
    desired_position_delta: float
    side: str
    intent_type: str
    urgency: str
    reduce_only_required: bool
    max_slippage_bps: float
    max_spread_bps: float
    max_participation_rate: float
    funding_guard_policy: str
    liquidation_guard_policy: str
    created_at: str
    expires_at: str

    @classmethod
    def create(
        cls,
        *,
        artifact_id: str,
        portfolio_plan_id: str,
        symbol: str,
        desired_position_delta: float,
        side: str,
        intent_type: str,
        urgency: str,
        reduce_only_required: bool,
        max_slippage_bps: float,
        max_spread_bps: float,
        max_participation_rate: float,
        funding_guard_policy: str,
        liquidation_guard_policy: str,
        created_at: str,
        expires_at: str,
    ) -> "InternalOrderIntent":
        payload = {
            "artifact_id": artifact_id,
            "portfolio_plan_id": portfolio_plan_id,
            "symbol": symbol,
            "desired_position_delta": desired_position_delta,
            "side": side.upper(),
            "intent_type": intent_type,
            "urgency": urgency,
            "reduce_only_required": reduce_only_required,
            "max_slippage_bps": max_slippage_bps,
            "max_spread_bps": max_spread_bps,
            "max_participation_rate": max_participation_rate,
            "funding_guard_policy": funding_guard_policy,
            "liquidation_guard_policy": liquidation_guard_policy,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        return cls(intent_id=_stable_hash(payload)[:48], **payload)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InternalOrderIntentValidation:
    passed: bool
    issues: list[str]


def validate_internal_order_intent(intent: InternalOrderIntent) -> InternalOrderIntentValidation:
    issues: list[str] = []
    for field_name in ("intent_id", "artifact_id", "portfolio_plan_id", "symbol", "created_at", "expires_at"):
        if not getattr(intent, field_name):
            issues.append(f"missing_{field_name}")
    if intent.side not in VALID_SIDES:
        issues.append("invalid_side")
    if intent.intent_type not in VALID_INTENT_TYPES:
        issues.append("invalid_intent_type")
    if intent.urgency not in VALID_URGENCY:
        issues.append("invalid_urgency")
    if intent.reduce_only_required and intent.side != "SELL":
        issues.append("reduce_only_side_mismatch")
    if not math.isfinite(float(intent.desired_position_delta)):
        issues.append("non_finite_desired_position_delta")
    if intent.desired_position_delta == 0:
        issues.append("zero_desired_position_delta")
    risk_bounds = (intent.max_slippage_bps, intent.max_spread_bps, intent.max_participation_rate)
    if not all(math.isfinite(float(value)) for value in risk_bounds):
        issues.append("non_finite_risk_bound")
    elif min(risk_bounds) < 0:
        issues.append("negative_risk_bound")
    if intent.max_participation_rate > 1.0:
        issues.append("participation_rate_gt_one")
    if not intent.funding_guard_policy:
        issues.append("missing_funding_guard_policy")
    if not intent.liquidation_guard_policy:
        issues.append("missing_liquidation_guard_policy")
    return InternalOrderIntentValidation(not issues, issues)


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
