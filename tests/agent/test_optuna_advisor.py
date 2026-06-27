from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.agent.optuna_advisor import build_optuna_plan


class _FakeTrial:
    def __init__(self, params: dict[str, float]) -> None:
        self.params = params

    def suggest_float(self, name: str, low: float, high: float, step: float | None = None) -> float:
        del low, high, step
        return float(self.params[name])

    def suggest_int(self, name: str, low: int, high: int, step: int = 1) -> int:
        del low, high, step
        return int(self.params[name])


class _FakeStudy:
    def __init__(self) -> None:
        self.best_params: dict[str, float] = {}
        self.best_value: float = float("-inf")
        self.enqueued_trials: list[dict[str, float | int]] = []
        self.optimize_calls: list[int] = []

    def enqueue_trial(self, params: dict[str, float | int]) -> None:
        self.enqueued_trials.append(dict(params))

    def optimize(self, objective, n_trials: int) -> None:
        self.optimize_calls.append(n_trials)
        candidate_params = [
            {"aggressiveness": 1.0},
            {"aggressiveness": 2.0},
            {"aggressiveness": 3.0},
        ][:n_trials]
        for params in candidate_params:
            score = float(objective(_FakeTrial(params)))
            if score >= self.best_value:
                self.best_value = score
                self.best_params = dict(params)


class OptunaAdvisorTests(unittest.TestCase):
    def test_build_optuna_plan_returns_best_parameters(self) -> None:
        fake_optuna = type(
            "FakeOptuna",
            (),
            {
                "samplers": type("Samplers", (), {"TPESampler": lambda self=None, seed=None: {"seed": seed}}),
                "pruners": type("Pruners", (), {"MedianPruner": lambda self=None, **kwargs: dict(kwargs)}),
                "create_study": staticmethod(lambda direction, sampler, pruner: _FakeStudy()),
            },
        )()

        with patch("engine.agent.optuna_advisor.optuna", fake_optuna):
            plan = build_optuna_plan(
                layer_name="kama",
                parameter_grid={
                    "aggressiveness": {"minimum": 1.0, "maximum": 3.0, "step": 1.0},
                },
                warm_start_trials=[],
                objective=lambda params: {"score": float(params["aggressiveness"])},
                n_trials=3,
                seed=7,
            )

        self.assertEqual(plan["best_parameters"]["aggressiveness"], 3.0)
        self.assertEqual(plan["planner_mode"], "optuna")

    def test_build_optuna_plan_enqueues_memory_seeded_trials(self) -> None:
        fake_study = _FakeStudy()
        fake_optuna = type(
            "FakeOptuna",
            (),
            {
                "samplers": type("Samplers", (), {"TPESampler": lambda self=None, seed=None: {"seed": seed}}),
                "pruners": type("Pruners", (), {"MedianPruner": lambda self=None, **kwargs: dict(kwargs)}),
                "create_study": staticmethod(lambda direction, sampler, pruner: fake_study),
            },
        )()

        with patch("engine.agent.optuna_advisor.optuna", fake_optuna):
            build_optuna_plan(
                layer_name="kama",
                parameter_grid={
                    "aggressiveness": {"minimum": 1.0, "maximum": 3.0, "step": 1.0},
                },
                warm_start_trials=[{"aggressiveness": 2.0}],
                objective=lambda params: {"score": float(params["aggressiveness"])},
                n_trials=3,
                seed=7,
            )

        self.assertEqual(fake_study.enqueued_trials, [{"aggressiveness": 2.0}])

    def test_build_optuna_plan_applies_sampler_pruner_and_trial_summary(self) -> None:
        fake_study = _FakeStudy()
        sampler_calls: list[tuple[str, int]] = []
        pruner_calls: list[tuple[str, dict[str, object]]] = []
        created_studies: list[dict[str, object]] = []

        class _FakePruned(Exception):
            pass

        fake_optuna = type(
            "FakeOptuna",
            (),
            {
                "TrialPruned": _FakePruned,
                "samplers": type(
                    "Samplers",
                    (),
                    {
                        "TPESampler": lambda self=None, seed=None: sampler_calls.append(("tpe", int(seed))) or {"kind": "tpe", "seed": seed},
                        "RandomSampler": lambda self=None, seed=None: sampler_calls.append(("random", int(seed))) or {"kind": "random", "seed": seed},
                    },
                ),
                "pruners": type(
                    "Pruners",
                    (),
                    {
                        "MedianPruner": lambda self=None, **kwargs: pruner_calls.append(("median", dict(kwargs))) or dict(kwargs),
                        "NopPruner": lambda self=None: pruner_calls.append(("nop", {})) or {"kind": "nop"},
                    },
                ),
                "create_study": staticmethod(
                    lambda direction, sampler, pruner: created_studies.append(
                        {"direction": direction, "sampler": sampler, "pruner": pruner}
                    )
                    or fake_study
                ),
            },
        )()

        with patch("engine.agent.optuna_advisor.optuna", fake_optuna):
            plan = build_optuna_plan(
                layer_name="kama",
                parameter_grid={
                    "aggressiveness": {"minimum": 1.0, "maximum": 3.0, "step": 1.0},
                },
                warm_start_trials=[{"aggressiveness": 2.0}, {"aggressiveness": 2.0}],
                objective=lambda params: {
                    "score": float(params["aggressiveness"]),
                    "train_score": float(params["aggressiveness"]) - 0.5,
                },
                n_trials=3,
                seed=11,
                sampler_name="random",
                pruner_enabled=False,
                startup_trials=4,
            )

        self.assertEqual(sampler_calls, [("random", 11)])
        self.assertEqual(pruner_calls, [("nop", {})])
        self.assertEqual(created_studies[0]["direction"], "maximize")
        self.assertEqual(plan["sampler"], "random")
        self.assertFalse(plan["pruner_enabled"])
        self.assertEqual(plan["startup_trials"], 4)
        self.assertEqual(plan["trial_count"], 3)
        self.assertEqual(plan["warm_start_trial_count"], 1)
        self.assertEqual(len(plan["search_summary"]), 3)
        self.assertEqual(plan["search_summary"][-1]["parameters"]["aggressiveness"], 3.0)
        self.assertEqual(plan["search_summary"][-1]["train_score"], 2.5)


if __name__ == "__main__":
    unittest.main()
