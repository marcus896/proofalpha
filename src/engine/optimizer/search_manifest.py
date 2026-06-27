from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchManifest:
    search_id: str
    layer_name: str
    parameter_space_hash: str
    budget_id: str
