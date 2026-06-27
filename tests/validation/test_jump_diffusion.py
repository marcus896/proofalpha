import unittest

from engine.validation.jump_diffusion import estimate_jump_params, generate_jump_stress_path


class JumpDiffusionTests(unittest.TestCase):
    def test_estimate_jump_params_detects_jumpier_series(self) -> None:
        calm = [0.001, 0.002, 0.0015, 0.0012, 0.0018]
        jumpy = [0.001, 0.002, -0.12, 0.0015, 0.09, 0.001]

        calm_params = estimate_jump_params(calm)
        jumpy_params = estimate_jump_params(jumpy)

        self.assertGreater(jumpy_params.jump_intensity, calm_params.jump_intensity)
        self.assertGreaterEqual(jumpy_params.jump_volatility, calm_params.jump_volatility)

    def test_generate_jump_stress_path_is_seeded_and_positive(self) -> None:
        params = estimate_jump_params([0.01, -0.08, 0.012, 0.09, -0.011, 0.013])

        path_a = generate_jump_stress_path(params, n_bars=8, seed=7, start_price=100.0)
        path_b = generate_jump_stress_path(params, n_bars=8, seed=7, start_price=100.0)

        self.assertEqual(path_a, path_b)
        self.assertEqual(len(path_a), 8)
        self.assertTrue(all(value > 0.0 for value in path_a))


if __name__ == "__main__":
    unittest.main()
