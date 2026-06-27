from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class ArtifactSignature:
    artifact_id: str
    content_hash: str
    config_hash: str
    strategy_graph_hash: str
    validation_bundle_hash: str
    signature_version: str

    def digest(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
