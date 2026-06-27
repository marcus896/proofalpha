import unittest

from engine.validation.hawkes import fit_hawkes_intensity, hawkes_cascade_multiplier


class HawkesCalibrationTests(unittest.TestCase):
    def test_fit_hawkes_intensity_rewards_clustered_events(self) -> None:
        sparse = fit_hawkes_intensity([0.0, 12.0, 24.0], [10.0, 10.0, 10.0])
        clustered = fit_hawkes_intensity([0.0, 0.5, 1.0], [10.0, 20.0, 30.0])

        self.assertGreater(clustered.branching_ratio, sparse.branching_ratio)
        self.assertGreater(clustered.excitation, sparse.excitation)

    def test_hawkes_cascade_multiplier_is_bounded_above_one(self) -> None:
        params = fit_hawkes_intensity([0.0, 0.5, 1.0], [10.0, 20.0, 30.0])
        multiplier = hawkes_cascade_multiplier(params, oi_concentration=0.8)

        self.assertGreaterEqual(multiplier, 1.0)


if __name__ == "__main__":
    unittest.main()
