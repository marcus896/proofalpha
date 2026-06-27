from __future__ import annotations

from itertools import product

from engine.config.models import ParameterRange


class GridSearchLimitError(ValueError):
    """Raised when a grid expansion exceeds the configured cap."""


def expand_parameter_grid(
    parameter_ranges: dict[str, ParameterRange],
    max_permutations: int,
) -> tuple[list[dict[str, float | int]], int]:
    if not parameter_ranges:
        return ([{}], 1)

    ordered_keys = list(parameter_ranges.keys())
    ordered_values = [parameter_ranges[key].values() for key in ordered_keys]

    count = 1
    for values in ordered_values:
        count *= len(values)
        if count > max_permutations:
            raise GridSearchLimitError(
                f"grid expansion would create {count} permutations, exceeding {max_permutations}"
            )

    grid = [
        dict(zip(ordered_keys, combination, strict=True))
        for combination in product(*ordered_values)
    ]
    return grid, count

