from __future__ import annotations

import unittest
from pathlib import Path

from engine.config.models import LayerFamily, LayerSpec, ParameterRange, StrategyGraph


class StrategyDeadWrapperTests(unittest.TestCase):
    def test_low_confidence_strategy_wrapper_modules_are_removed(self) -> None:
        strategy_dir = Path("src") / "engine" / "strategy"

        self.assertFalse((strategy_dir / "graphs.py").exists())
        self.assertFalse((strategy_dir / "layers.py").exists())

    def test_canonical_strategy_models_cover_removed_wrapper_api(self) -> None:
        threshold = ParameterRange(minimum=1.0, maximum=3.0, step=1.0)
        layer = LayerSpec(
            name="kama",
            family=LayerFamily.DIRECTIONAL_FILTER,
            parameters={"threshold": threshold},
            precedence=1,
        )
        graph = StrategyGraph(backbone="mom_squeeze", layers=[layer])

        self.assertEqual(graph.backbone, "mom_squeeze")
        self.assertEqual(graph.layers[0].name, "kama")
        self.assertEqual(graph.layers[0].parameters["threshold"].maximum, 3.0)


if __name__ == "__main__":
    unittest.main()
