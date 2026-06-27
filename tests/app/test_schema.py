import json
import subprocess
import unittest
from pathlib import Path

from engine.app.schema import build_study_schema


class StudySchemaTests(unittest.TestCase):
    def test_build_study_schema_describes_runtime_and_layer_parameters(self) -> None:
        schema = build_study_schema()

        self.assertEqual(schema["type"], "object")
        self.assertIn("runtime", schema["properties"])
        self.assertIn("layer_parameters", schema["properties"])
        self.assertIn("snapshot", schema["required"])
        self.assertIn("run_id", schema["required"])
        self.assertEqual(
            schema["properties"]["runtime"]["properties"]["mode"]["enum"],
            ["builtin", "fixture"],
        )
        self.assertEqual(
            schema["properties"]["runtime"]["properties"]["position_side"]["enum"],
            ["long", "short"],
        )
        self.assertIn(
            "fail_on_quality_flags",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "position_leverage",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "maintenance_margin_ratio",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "liquidation_fee_bps",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "liquidation_mark_price_weight",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "partial_liquidation_ratio",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "liquidation_cooldown_bars",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "liquidation_step_schedule",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "liquidation_mark_premium_bps",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "maintenance_margin_schedule",
            schema["properties"]["runtime"]["properties"],
        )
        self.assertIn(
            "liquidation_fee_schedule",
            schema["properties"]["runtime"]["properties"],
        )
        scenario_properties = schema["properties"]["scenarios"]["items"]["properties"]
        self.assertIn("funding_multiplier", scenario_properties)
        self.assertIn("liquidity_penalty_bps", scenario_properties)
        self.assertIn("latency_delta_bars", scenario_properties)
        self.assertIn("drawdown_multiplier", scenario_properties)
        self.assertIn("mark_premium_bps", scenario_properties)
        self.assertIn(
            "entry_stride",
            schema["properties"]["layer_parameters"]["additionalProperties"]["properties"],
        )
        parameter_grid_schema = schema["properties"]["parameter_grids"]["additionalProperties"]["additionalProperties"]
        self.assertIn("excluded_values", parameter_grid_schema["properties"])

    def test_cli_export_schema_writes_json_schema_file(self) -> None:
        output_path = Path("test-study-schema.json")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "export-schema",
                    "--output",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        finally:
            if output_path.exists():
                output_path.unlink()

        self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("snapshot", payload["properties"])
        self.assertIn("runtime", payload["properties"])


if __name__ == "__main__":
    unittest.main()
