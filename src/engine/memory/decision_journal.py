from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json


@dataclass(frozen=True)
class DecisionJournal:
    decision_id: str
    actor: str
    decision_type: str
    input_hash: str
    output_hash: str
    reason: str
    created_at: str

    @staticmethod
    def record(
        *,
        decision_id: str,
        actor: str,
        decision_type: str,
        input_payload: dict[str, object],
        output_payload: dict[str, object],
        reason: str,
    ) -> "DecisionJournal":
        return DecisionJournal(
            decision_id=decision_id,
            actor=actor,
            decision_type=decision_type,
            input_hash=_hash(input_payload),
            output_hash=_hash(output_payload),
            reason=reason,
            created_at=datetime.now(UTC).isoformat(),
        )


def _hash(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
