from __future__ import annotations

from dataclasses import dataclass


PRIVATE_KEY_TOKENS = ("API_KEY", "SECRET", "PRIVATE_KEY")


@dataclass(frozen=True)
class GuardResult:
    passed: bool
    reasons: list[str]


class SecretsGuard:
    def scan(self, config: dict[str, object]) -> GuardResult:
        reasons = [f"private_key_field:{path}" for path in _secret_field_paths(config)]
        return GuardResult(not reasons, reasons)


def _secret_field_paths(value: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            if any(token in key.upper() for token in PRIVATE_KEY_TOKENS):
                paths.append(path)
            paths.extend(_secret_field_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(_secret_field_paths(child, path))
    return paths
