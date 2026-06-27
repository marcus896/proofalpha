from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class StrategyFreezeManifest:
    artifact_id: str
    strategy_graph_hash: str
    feature_contract_hash: str
    code_version: str
    config_hash: str
    validation_bundle_hash: str
    created_at: str
    expiry_time: str
    frozen_by: str

    def manifest_hash(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
