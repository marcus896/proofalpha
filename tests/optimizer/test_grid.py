import unittest

from engine.config.models import ParameterRange
from engine.optimizer.grid import GridSearchLimitError, expand_parameter_grid


class GridExpansionTests(unittest.TestCase):
    def test_excludes_parameter_values_before_cartesian_expansion(self) -> None:
        grid, count = expand_parameter_grid(
            {
                "fast": ParameterRange(minimum=1, maximum=5, step=1, excluded_values=[2, 4]),
            },
            max_permutations=10,
        )

        self.assertEqual(count, 3)
        self.assertEqual(grid, [{"fast": 1}, {"fast": 3}, {"fast": 5}])

    def test_expands_cartesian_product_and_counts_permutations(self) -> None:
        grid, count = expand_parameter_grid(
            {
                "fast": ParameterRange(minimum=20, maximum=60, step=20),
                "slow": ParameterRange(minimum=40, maximum=80, step=20),
            },
            max_permutations=100,
        )

        self.assertEqual(count, 9)
        self.assertEqual(grid[0], {"fast": 20, "slow": 40})
        self.assertEqual(grid[-1], {"fast": 60, "slow": 80})

    def test_raises_when_permutation_limit_is_exceeded(self) -> None:
        with self.assertRaises(GridSearchLimitError):
            expand_parameter_grid(
                {
                    "a": ParameterRange(minimum=1, maximum=10, step=1),
                    "b": ParameterRange(minimum=1, maximum=10, step=1),
                    "c": ParameterRange(minimum=1, maximum=10, step=1),
                },
                max_permutations=500,
            )


if __name__ == "__main__":
    unittest.main()
