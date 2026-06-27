from __future__ import annotations


def diff_config(before: dict[str, object], after: dict[str, object]) -> dict[str, dict[str, object]]:
    diff: dict[str, dict[str, object]] = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            diff[key] = {"before": before.get(key), "after": after.get(key)}
    return diff
