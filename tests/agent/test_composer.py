import unittest

from engine.agent.composer import AdvisoryInput, build_advisory_variants
from engine.app.schema import build_study_schema
from engine.mcp.config import MCPProfile
from engine.strategy.catalog import catalog_by_family


def _base_payload() -> dict[str, object]:
    return {
        "run_id": "phase4-study",
        "seed": 7,
        "snapshot": {
            "snapshot_id": "phase4-snap",
            "symbol": "SOLUSDT",
            "venue": "binance",
            "timeframe": "1h",
            "candles": [],
            "funding_rates": [],
            "open_interest": [],
            "liquidation_notional": [],
            "maker_fee_bps": 2.0,
            "taker_fee_bps": 5.0,
        },
        "incumbent": {"backbone": "mom_squeeze", "layers": ["kama"]},
        "directional_layers": ["kama", "rogue_layer", "ema"],
        "known_good_filters": ["flat9"],
        "custom_filters": [],
        "exit_layers": ["time_stop"],
        "parameter_grids": {
            "kama": {
                "aggressiveness": {"minimum": 1.0, "maximum": 3.0, "step": 1.0},
            },
        },
        "runtime": {
            "mode": "builtin",
            "bootstrap_samples": 8,
            "search_summary_limit": 3,
        },
        "scenarios": [
            {"name": "short-squeeze", "severity": 0.8, "description": "Short squeeze"},
            {"name": "venue-outage", "severity": 0.7, "description": "Venue outage"},
        ],
    }


class AdvisoryComposerTests(unittest.TestCase):
    def test_build_advisory_variants_emits_bounded_rationale_and_filters_unapproved_layers(self) -> None:
        advisory_input = AdvisoryInput(
            base_payload=_base_payload(),
            memory_summary={
                "promising_layers": [{"layer_name": "ema", "count": 3}],
                "fragile_layers": [{"layer_name": "time_stop", "count": 2}],
                "parameter_hints": {
                    "kama": {
                        "aggressiveness": {
                            "minimum": 2.0,
                            "maximum": 2.0,
                            "promoted_count": 2,
                            "blocked_values": [1.0],
                            "confidence": "high",
                            "narrowed": True,
                        }
                    }
                },
                "validation_failures": [{"gate_name": "walk_forward_permutation", "count": 2}],
                "failure_taxonomy_counts": {
                    "holdout_failure": 2,
                    "stress_failure": 1,
                },
                "stop_reason": "repeated_holdout_failures",
                "next_hypotheses": ["raise_holdout_robustness", "harden_stress_scenarios"],
                "regime_coverage_gaps": [{"regime_label": "short_squeeze", "average_coverage": 0.02, "count": 2}],
                "scenario_profile_avoidance": {
                    "venue-outage": {
                        "count": 2,
                        "profile": {"name": "venue-outage", "severity": 0.7, "description": "Venue outage"},
                    }
                },
                "runtime_profile_hints": {
                    "count": 2,
                    "profile": {"slippage_bps": 4.0},
                },
                "top_duplicate_matches": [{"run_id": "baseline-a", "count": 2}],
                "upstream_adaptation_summary": {
                    "linked_resource_count": 2,
                    "blocked_resource_count": 1,
                    "provenance_gap_count": 0,
                    "linked_resources": [
                        {
                            "resource_id": "finrl_crypto",
                            "title": "FinRL Crypto",
                            "intended_usage": "adapter_only",
                            "license": "MIT",
                            "status": "cloned_pinned",
                            "run_ids": ["phase4-study"],
                            "link_roles": ["snapshot_provenance"],
                            "evidence_sources": ["snapshot_provenance"],
                        },
                        {
                            "resource_id": "openbb",
                            "title": "OpenBB",
                            "intended_usage": "reference_only",
                            "license": "AGPL-3.0",
                            "status": "blocked_license_review",
                            "run_ids": ["phase4-study"],
                            "link_roles": ["validation_reference"],
                            "evidence_sources": ["validation_bundle"],
                        },
                    ],
                    "blocked_resource_ids": ["openbb"],
                    "provenance_gap_resource_ids": [],
                },
                "upstream_governance": {
                    "has_blocked_resources": True,
                    "has_provenance_gaps": False,
                    "recommended_stop_reason": "resource_license_risk",
                },
            },
            layer_catalog=catalog_by_family(),
            study_schema=build_study_schema(),
            skill_contracts=[
                {
                    "name": "strategy-composer",
                    "purpose": "compose legal candidate strategies",
                    "outputs": ["candidate study payloads with bounded parameters"],
                    "rules": ["may only use approved `LayerSpec` families"],
                }
            ],
            mcp_environment={
                "profile": MCPProfile.READ_ONLY.value,
                "tool_categories": ["schema", "validation"],
                "tool_names": ["list_layers", "get_layer", "get_validation_protocol"],
                "launcher_enabled": False,
            },
            duplicate_baseline_history_by_variant={
                "conservative": {
                    "sample_count": 2,
                    "promoted_count": 2,
                    "success_rate": 1.0,
                    "average_sharpe": 0.6,
                    "duplicate_baseline_run_id": "baseline-a",
                }
            },
        )

        variants = build_advisory_variants(advisory_input)

        balanced = variants["balanced"]
        conservative = variants["conservative"]

        self.assertEqual(balanced["directional_layers"], ["ema", "kama"])
        self.assertNotIn("rogue_layer", balanced["directional_layers"])
        self.assertEqual(balanced["exit_layers"], [])
        self.assertEqual(balanced["parameter_grids"]["kama"]["aggressiveness"]["minimum"], 2.0)
        self.assertEqual(balanced["parameter_grids"]["kama"]["aggressiveness"]["maximum"], 2.0)
        self.assertEqual(balanced["parameter_avoidance"]["kama"]["aggressiveness"], [1.0])
        self.assertEqual(balanced["runtime"]["slippage_bps"], 4.0)
        self.assertEqual(balanced["research_lineage"]["selected_variant"], "balanced")

        rationale = balanced["advisory_rationale"]
        self.assertEqual(rationale["variant"], "balanced")
        self.assertIn("bounded", rationale["summary"])
        self.assertIn("repeated_holdout_failures", rationale["summary"])
        self.assertIn("raise_holdout_robustness", rationale["summary"])
        self.assertIn("approved layer catalog only", rationale["constraints"])
        evidence_types = [item["type"] for item in rationale["evidence"]]
        self.assertIn("promising_layer", evidence_types)
        self.assertIn("validation_failure", evidence_types)
        self.assertIn("failure_taxonomy", evidence_types)
        self.assertIn("stop_reason", evidence_types)
        self.assertIn("next_hypothesis", evidence_types)
        self.assertIn("regime_coverage_gap", evidence_types)
        self.assertIn("duplicate_baseline", evidence_types)
        self.assertIn("upstream_resource", evidence_types)
        self.assertIn("upstream_governance", evidence_types)

        hypotheses = balanced["research_hypotheses"]
        self.assertEqual(hypotheses["failure_taxonomy_counts"]["holdout_failure"], 2)
        self.assertEqual(hypotheses["stop_reason"], "repeated_holdout_failures")
        self.assertEqual(
            hypotheses["next_hypotheses"],
            ["raise_holdout_robustness", "harden_stress_scenarios"],
        )

        context = balanced["advisory_context"]
        self.assertEqual(context["study_schema_title"], "ProofAlpha Study")
        self.assertIn("directional_layers", context["layer_catalog"])
        self.assertEqual(context["duplicate_baseline_run_id"], "baseline-a")
        self.assertEqual(context["agent_environment"]["mcp"]["profile"], "read_only")
        self.assertEqual(context["agent_environment"]["skills"][0]["name"], "strategy-composer")
        self.assertIn("list_layers", context["agent_environment"]["mcp"]["tool_names"])
        self.assertEqual(context["agent_environment"]["loop_policy"]["default_mode"], "auto")
        self.assertEqual(context["agent_environment"]["loop_policy"]["recommended_mode_for_payload"], "bounded")
        self.assertIn("python_source", context["agent_environment"]["loop_policy"]["karpathy_when"])
        self.assertIn("full validation", context["agent_environment"]["loop_policy"]["bounded_when"])
        upstream = context["agent_environment"]["upstream_adaptation"]
        self.assertEqual(upstream["linked_resource_count"], 2)
        self.assertEqual(upstream["blocked_resource_count"], 1)
        self.assertEqual(upstream["linked_resources"][0]["resource_id"], "finrl_crypto")
        self.assertEqual(upstream["linked_resources"][1]["resource_id"], "openbb")

        self.assertGreaterEqual(conservative["runtime"]["bootstrap_samples"], 16)


if __name__ == "__main__":
    unittest.main()
