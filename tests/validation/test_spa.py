from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass
from unittest.mock import patch


@dataclass(eq=True)
class _FakeArray:
    data: object
    dtype: object
    kind: str = "asarray"

    @property
    def T(self) -> _FakeArray:
        return _FakeArray(self.data, self.dtype, kind="transpose")

    def tolist(self) -> object:
        if self.kind == "transpose" and isinstance(self.data, list) and self.data and isinstance(self.data[0], list):
            return [list(column) for column in zip(*self.data)]
        return self.data


def _fake_asarray(data: object, dtype: object = float) -> _FakeArray:
    return _FakeArray(data, dtype)


try:
    import numpy as _numpy  # type: ignore[import-not-found]
except ModuleNotFoundError:
    _numpy = None

if _numpy is None or not hasattr(_numpy, "asarray"):
    _numpy = types.ModuleType("numpy")
    _numpy.asarray = _fake_asarray  # type: ignore[attr-defined]
    sys.modules["numpy"] = _numpy

from engine.validation.spa import run_spa_test


class SpaAdaptorTests(unittest.TestCase):
    def test_run_spa_test_returns_skipped_when_arch_is_missing(self) -> None:
        with patch("engine.validation.spa._load_spa_class", return_value=None):
            result = run_spa_test(
                benchmark=[0.01, 0.02, 0.00, -0.01],
                models=[[0.02, 0.03, 0.01, 0.00]],
                block_size=2,
                reps=100,
            )
        self.assertEqual(
            result,
            {
                "status": "skipped",
                "available": False,
                "enforced": False,
                "pvalues": [],
                "rejections": [],
            },
        )

    def test_run_spa_test_returns_pvalues_when_arch_is_available(self) -> None:
        class FakeSpa:
            last_instance: FakeSpa | None = None

            def __init__(self, benchmark, models, block_size, reps):
                self.benchmark = benchmark
                self.models = models
                self.block_size = block_size
                self.reps = reps
                self.computed = False
                FakeSpa.last_instance = self

            def compute(self):
                self.computed = True

            @property
            def pvalues(self):
                if not self.computed:
                    raise AssertionError("compute() must be called before pvalues")
                return [0.04]

        with patch("engine.validation.spa._load_spa_class", return_value=FakeSpa):
            result = run_spa_test(
                benchmark=[0.01, 0.02, 0.00, -0.01],
                models=[[0.02, 0.03, 0.01, 0.00]],
                block_size=2,
                reps=100,
            )

        self.assertEqual(
            result,
            {
                "status": "ok",
                "available": True,
                "enforced": True,
                "pvalues": [0.04],
                "rejections": [True],
            },
        )
        self.assertEqual(
            FakeSpa.last_instance.benchmark.tolist(),
            [0.01, 0.02, 0.0, -0.01],
        )
        self.assertEqual(
            FakeSpa.last_instance.models.tolist(),
            [[0.02], [0.03], [0.01], [0.0]],
        )
        self.assertEqual(FakeSpa.last_instance.benchmark.dtype, float)
        self.assertEqual(FakeSpa.last_instance.models.dtype, float)
        self.assertEqual(FakeSpa.last_instance.block_size, 2)
        self.assertEqual(FakeSpa.last_instance.reps, 100)
        self.assertTrue(FakeSpa.last_instance.computed)


if __name__ == "__main__":
    unittest.main()
