"""Tests for the tsbootstrap adaptor layer.

These tests avoid real ``tsbootstrap`` and ``numpy`` dependencies by using
small deterministic in-test shims for the optional dependency boundary.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import engine.validation.bootstrap as bootstrap_module
from engine.validation.bootstrap import (
    TSBOOTSTRAP_AVAILABLE,
    SUPPORTED_BOOTSTRAP_METHODS,
    bootstrap_indices_for_method,
    list_bootstrap_methods,
    moving_block_bootstrap_indices,
    stationary_block_bootstrap_indices,
)


class _FakeArray1D:
    def __init__(self, values):
        self._values = list(values)

    def flatten(self):
        return self

    def tolist(self):
        return list(self._values)

    def __len__(self) -> int:
        return len(self._values)


class _FakeNP:
    @staticmethod
    def arange(stop: int, dtype=float):
        return _FakeArray1D(range(stop))

    @staticmethod
    def asarray(values):
        if isinstance(values, _FakeArray1D):
            return values
        return _FakeArray1D(values)


class TestTsbootstrapSentinel(unittest.TestCase):
    def test_tsbootstrap_available_is_bool(self) -> None:
        self.assertIsInstance(TSBOOTSTRAP_AVAILABLE, bool)

    def test_supported_bootstrap_methods_contains_stdlib_always(self) -> None:
        methods = set(SUPPORTED_BOOTSTRAP_METHODS)
        self.assertIn("dependent_wild", methods)
        self.assertIn("moving_block", methods)
        self.assertIn("stationary_block", methods)

    def test_supported_bootstrap_methods_contains_tsbootstrap_names(self) -> None:
        methods = set(SUPPORTED_BOOTSTRAP_METHODS)
        self.assertIn("tsbootstrap_moving_block", methods)
        self.assertIn("tsbootstrap_stationary_block", methods)

    def test_supported_bootstrap_methods_is_sorted_tuple(self) -> None:
        self.assertEqual(list(SUPPORTED_BOOTSTRAP_METHODS), sorted(SUPPORTED_BOOTSTRAP_METHODS))


class TestListBootstrapMethods(unittest.TestCase):
    def setUp(self) -> None:
        self.methods = list_bootstrap_methods()

    def test_returns_dict(self) -> None:
        self.assertIsInstance(self.methods, dict)

    def test_stdlib_methods_always_available(self) -> None:
        self.assertTrue(self.methods.get("dependent_wild"))
        self.assertTrue(self.methods.get("moving_block"))
        self.assertTrue(self.methods.get("stationary_block"))

    def test_tsbootstrap_methods_availability_matches_sentinel(self) -> None:
        for name in ("tsbootstrap_moving_block", "tsbootstrap_stationary_block"):
            self.assertIn(name, self.methods)
            self.assertEqual(self.methods[name], TSBOOTSTRAP_AVAILABLE)

    def test_all_values_are_bools(self) -> None:
        for name, available in self.methods.items():
            self.assertIsInstance(available, bool)

    def test_all_supported_methods_are_listed(self) -> None:
        for method in SUPPORTED_BOOTSTRAP_METHODS:
            self.assertIn(method, self.methods)


class TestStdlibMethodsUnaffected(unittest.TestCase):
    def test_moving_block_is_deterministic(self) -> None:
        self.assertEqual(
            moving_block_bootstrap_indices(sample_count=20, block_size=4, seed=99),
            moving_block_bootstrap_indices(sample_count=20, block_size=4, seed=99),
        )

    def test_stationary_block_is_deterministic(self) -> None:
        self.assertEqual(
            stationary_block_bootstrap_indices(sample_count=20, block_size=4, seed=99),
            stationary_block_bootstrap_indices(sample_count=20, block_size=4, seed=99),
        )

    def test_dispatch_moving_block_via_method_string(self) -> None:
        indices = bootstrap_indices_for_method("moving_block", 20, 4, seed=7)
        self.assertEqual(len(indices), 20)
        self.assertTrue(all(0 <= i < 20 for i in indices))

    def test_dispatch_stationary_block_via_method_string(self) -> None:
        indices = bootstrap_indices_for_method("stationary_block", 20, 4, seed=7)
        self.assertEqual(len(indices), 20)
        self.assertTrue(all(0 <= i < 20 for i in indices))

    def test_unknown_method_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported bootstrap method"):
            bootstrap_indices_for_method("totally_unknown", 20, 4, seed=7)

    def test_unknown_method_error_includes_method_name(self) -> None:
        try:
            bootstrap_indices_for_method("bogus_method", 20, 4, seed=7)
        except ValueError as exc:
            self.assertIn("bogus_method", str(exc))


class TestTsbootstrapAdaptor(unittest.TestCase):
    def _patch_fake_tsbootstrap(self):
        class _FakeBlockBootstrap:
            def __init__(
                self,
                n_bootstraps: int,
                block_length: int,
                block_length_distribution,
                wrap_around_flag: bool,
                overlap_flag: bool,
                rng: int,
            ) -> None:
                self.block_length = block_length
                self.rng = rng

            def bootstrap(self, arr):
                import random

                sample_count = len(arr)
                rng = random.Random(self.rng)
                indices: list[int] = []
                max_start = max(0, sample_count - self.block_length)
                while len(indices) < sample_count:
                    start = rng.randint(0, max_start)
                    indices.extend(range(start, start + self.block_length))
                yield _FakeArray1D(indices[:sample_count])

        return patch.multiple(
            bootstrap_module,
            TSBOOTSTRAP_AVAILABLE=True,
            _np=_FakeNP,
            _BlockBootstrap=_FakeBlockBootstrap,
        )

    def test_tsbootstrap_moving_block_raises_import_error_when_forced_unavailable(self) -> None:
        with patch.object(bootstrap_module, "TSBOOTSTRAP_AVAILABLE", False):
            with self.assertRaises(ImportError) as ctx:
                bootstrap_indices_for_method("tsbootstrap_moving_block", 20, 4, seed=7)
        self.assertIn("tsbootstrap", str(ctx.exception).lower())
        self.assertIn("pip install", str(ctx.exception))

    def test_tsbootstrap_stationary_block_raises_import_error_when_forced_unavailable(self) -> None:
        with patch.object(bootstrap_module, "TSBOOTSTRAP_AVAILABLE", False):
            with self.assertRaises(ImportError) as ctx:
                bootstrap_indices_for_method("tsbootstrap_stationary_block", 20, 4, seed=7)
        self.assertIn("tsbootstrap", str(ctx.exception).lower())

    def test_tsbootstrap_moving_block_returns_valid_indices_when_available(self) -> None:
        with self._patch_fake_tsbootstrap():
            indices = bootstrap_indices_for_method("tsbootstrap_moving_block", 30, 5, seed=42)
        self.assertEqual(len(indices), 30)
        self.assertTrue(all(0 <= i < 30 for i in indices))

    def test_tsbootstrap_stationary_block_returns_valid_indices_when_available(self) -> None:
        with self._patch_fake_tsbootstrap():
            indices = bootstrap_indices_for_method("tsbootstrap_stationary_block", 30, 5, seed=42)
        self.assertEqual(len(indices), 30)
        self.assertTrue(all(0 <= i < 30 for i in indices))

    def test_tsbootstrap_is_seeded_when_available(self) -> None:
        with self._patch_fake_tsbootstrap():
            first = bootstrap_indices_for_method("tsbootstrap_moving_block", 24, 4, seed=13)
            second = bootstrap_indices_for_method("tsbootstrap_moving_block", 24, 4, seed=13)
        self.assertEqual(first, second)

    def test_tsbootstrap_different_seeds_differ_when_available(self) -> None:
        with self._patch_fake_tsbootstrap():
            first = bootstrap_indices_for_method("tsbootstrap_moving_block", 24, 4, seed=1)
            second = bootstrap_indices_for_method("tsbootstrap_moving_block", 24, 4, seed=999)
        self.assertNotEqual(first, second)


class TestBootstrapMethodFieldInConfig(unittest.TestCase):
    def test_all_known_method_names_are_strings(self) -> None:
        for method in SUPPORTED_BOOTSTRAP_METHODS:
            self.assertIsInstance(method, str)
            self.assertTrue(method)

    def test_stdlib_methods_dispatch_without_import(self) -> None:
        for method in ("dependent_wild", "moving_block", "stationary_block"):
            self.assertEqual(len(bootstrap_indices_for_method(method, 16, 4, seed=3)), 16)


if __name__ == "__main__":
    unittest.main()
