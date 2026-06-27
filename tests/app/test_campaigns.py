import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock


WORKDIR = Path(__file__).resolve().parents[2]


class CampaignAndLoggingCliTests(unittest.TestCase):
    def test_run_campaign_manifest_reraises_keyboard_interrupt(self) -> None:
        import engine.app.cli as cli

        campaign_root = Path("test-output-cli-campaign-interrupt")
        manifest_path = campaign_root / "interrupt.manifest.json"
        config_path = campaign_root / "interrupt.config.json"
        report_path = campaign_root / "interrupt.campaign.json"
        campaign_root.mkdir(exist_ok=True)
        config_path.write_text("{}", encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "campaign_id": "interrupt-campaign",
                    "entries": [
                        {
                            "name": "baseline",
                            "command": "run",
                            "config": str(config_path.resolve()),
                            "output_dir": str((campaign_root / "baseline").resolve()),
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        class _DummyStudy:
            run_id = "interrupt-run"
            runtime_settings = type("_RuntimeSettings", (), {"fail_on_quality_flags": False})()
            snapshot = type("_Snapshot", (), {"quality_flags": [], "snapshot_id": "snap-1"})()

        try:
            with mock.patch("engine.app.cli.load_study_config", return_value=_DummyStudy()), mock.patch(
                "engine.app.cli._run_study_execution",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    cli._run_campaign_manifest(manifest_path, report_path)
        finally:
            if campaign_root.exists():
                shutil.rmtree(campaign_root)

    def test_cli_inspect_campaign_expands_defaults_and_matrix_entries(self) -> None:
        manifest_path = Path("test-output-cli-inspect-campaign.json")
        try:
            manifest_path.write_text(
                json.dumps(
                    {
                        "campaign_id": "inspect-campaign",
                        "vars": {
                            "root": "outputs/template-campaign",
                            "suffix": "study",
                        },
                        "defaults": {
                            "memory_limit": 11,
                            "memory_quality_policy": "all",
                            "strict_quality": True,
                        },
                        "entries": [
                            {
                                "name_template": "baseline-{variant}",
                                "command": "run",
                                "config": "examples/minimal_builtin_study.json",
                                "output_dir": "{root}/{variant}",
                                "matrix": [
                                    {"variant": "a"},
                                    {"variant": "b"},
                                ],
                            },
                            {
                                "name": "memory-pass",
                                "command": "autoresearch",
                                "config": "examples/minimal_builtin_study.json",
                                "output_dir": "{root}/{suffix}",
                            },
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "inspect-campaign",
                    "--manifest",
                    str(manifest_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Campaign inspect-campaign", completed.stdout)
            self.assertIn("Expanded entries: 3", completed.stdout)
            self.assertIn("1. baseline-a | run", completed.stdout)
            self.assertIn("2. baseline-b | run", completed.stdout)
            self.assertIn("3. memory-pass | autoresearch", completed.stdout)
            self.assertIn("memory_limit=11", completed.stdout)
            self.assertIn("strict_quality=True", completed.stdout)
        finally:
            if manifest_path.exists():
                manifest_path.unlink()

    def test_cli_run_campaign_supports_defaults_and_matrix_templates(self) -> None:
        campaign_root = Path("test-output-cli-template-campaign")
        manifest_path = Path("test-output-cli-template-campaign-manifest.json")
        baseline_config_path = Path("test-output-cli-template-baseline.json")
        memory_config_path = Path("test-output-cli-template-memory.json")
        report_path = campaign_root / "template-campaign.campaign.json"
        baseline_payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
        baseline_payload["run_id"] = "template-baseline"
        baseline_config_path.write_text(json.dumps(baseline_payload, indent=2, sort_keys=True), encoding="utf-8")
        memory_payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
        memory_payload["run_id"] = "template-memory"
        memory_config_path.write_text(json.dumps(memory_payload, indent=2, sort_keys=True), encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "campaign_id": "template-campaign",
                    "vars": {
                        "root": str(campaign_root),
                        "db_name": "campaign.sqlite",
                    },
                    "defaults": {
                        "db": "{root}/{db_name}",
                        "memory_limit": 9,
                        "memory_quality_policy": "all",
                    },
                    "entries": [
                        {
                            "name_template": "baseline-{variant}",
                            "command": "run",
                            "config": str(baseline_config_path),
                            "output_dir": "{root}/baseline-{variant}",
                            "matrix": [
                                {"variant": "a"},
                                {"variant": "b"},
                            ],
                        },
                        {
                            "name": "memory-pass",
                            "command": "autoresearch",
                            "config": str(memory_config_path),
                            "output_dir": "{root}/memory-pass",
                        },
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "run-campaign",
                    "--manifest",
                    str(manifest_path),
                    "--output-report",
                    str(report_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["campaign_id"], "template-campaign")
            self.assertEqual(payload["entry_count"], 3)
            self.assertEqual(payload["completed_entries"], 3)

            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual([entry["name"] for entry in report_payload["entries"]], ["baseline-a", "baseline-b", "memory-pass"])
            self.assertEqual(
                [entry["command"] for entry in report_payload["entries"]],
                ["run", "run", "autoresearch"],
            )
            self.assertNotEqual(report_payload["entries"][2]["status"], "failed")
            self.assertEqual(report_payload["entries"][2]["db_path"], str((campaign_root / "campaign.sqlite").resolve()))
            self.assertEqual(report_payload["entries"][2]["memory_limit"], 9)
            self.assertEqual(report_payload["entries"][2]["memory_quality_policy"], "all")
            self.assertEqual(report_payload["entries"][0]["template_values"]["variant"], "a")
            self.assertEqual(report_payload["entries"][1]["template_values"]["variant"], "b")
        finally:
            if manifest_path.exists():
                manifest_path.unlink()
            for config_path in (baseline_config_path, memory_config_path):
                if config_path.exists():
                    config_path.unlink()
            if campaign_root.exists():
                shutil.rmtree(campaign_root)

    def test_cli_run_writes_event_log(self) -> None:
        output_dir = Path("test-output-cli-run-log")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "run",
                    "--config",
                    "examples/minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertIn("log_path", payload)
            log_path = Path(payload["log_path"])
            self.assertTrue(log_path.exists())

            events = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            event_names = [event.get("event") for event in events]
            self.assertIn("study_loaded", event_names)
            self.assertIn("research_cycle_completed", event_names)
            self.assertIn("command_completed", event_names)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_autoresearch_writes_event_log(self) -> None:
        output_dir = Path("test-output-cli-autoresearch-log")
        db_path = Path("test-output-cli-autoresearch-log.sqlite")
        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "autoresearch",
                    "--config",
                    "examples/minimal_builtin_study.json",
                    "--output-dir",
                    str(output_dir),
                    "--db",
                    str(db_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertIn("log_path", payload)
            log_path = Path(payload["log_path"])
            self.assertTrue(log_path.exists())

            events = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            event_names = [event.get("event") for event in events]
            self.assertIn("study_loaded", event_names)
            self.assertIn("autoresearch_completed", event_names)
            self.assertIn("next_study_variants_materialized", event_names)
            self.assertIn("command_completed", event_names)
        finally:
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_run_campaign_executes_entries_and_summarizes(self) -> None:
        campaign_root = Path("test-output-cli-campaign")
        manifest_path = Path("test-output-cli-campaign-manifest.json")
        baseline_config_path = Path("test-output-cli-campaign-baseline.json")
        memory_config_path = Path("test-output-cli-campaign-memory.json")
        report_path = campaign_root / "smoke-campaign.campaign.json"
        db_path = Path("test-output-cli-campaign.sqlite")
        baseline_payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
        baseline_payload["run_id"] = "campaign-baseline"
        baseline_config_path.write_text(json.dumps(baseline_payload, indent=2, sort_keys=True), encoding="utf-8")
        memory_payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
        memory_payload["run_id"] = "campaign-memory"
        memory_config_path.write_text(json.dumps(memory_payload, indent=2, sort_keys=True), encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "campaign_id": "smoke-campaign",
                    "db": str(db_path),
                    "entries": [
                        {
                            "name": "baseline",
                            "command": "run",
                            "config": str(baseline_config_path),
                            "output_dir": str(campaign_root / "baseline"),
                        },
                        {
                            "name": "memory-pass",
                            "command": "autoresearch",
                            "config": str(memory_config_path),
                            "output_dir": str(campaign_root / "memory-pass"),
                        },
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "run-campaign",
                    "--manifest",
                    str(manifest_path),
                    "--output-report",
                    str(report_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["campaign_id"], "smoke-campaign")
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["entry_count"], 2)
            self.assertEqual(payload["completed_entries"], 2)
            self.assertIn("log_path", payload)
            self.assertTrue(Path(payload["log_path"]).exists())
            self.assertTrue(report_path.exists())

            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report_payload["campaign_id"], "smoke-campaign")
            self.assertEqual(len(report_payload["entries"]), 2)
            self.assertEqual(
                [entry["command"] for entry in report_payload["entries"]],
                ["run", "autoresearch"],
            )
            for entry in report_payload["entries"]:
                self.assertNotEqual(entry["status"], "failed")
                self.assertTrue(Path(entry["log_path"]).exists())

            summary_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "summarize-campaign",
                    "--campaign-report",
                    str(report_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(summary_completed.returncode, 0, msg=summary_completed.stderr)
            self.assertIn("Campaign smoke-campaign", summary_completed.stdout)
            self.assertIn("Entries: 2", summary_completed.stdout)
            self.assertIn("Completed entries: 2", summary_completed.stdout)
            self.assertIn("baseline | run |", summary_completed.stdout)
            self.assertIn("memory-pass | autoresearch |", summary_completed.stdout)
        finally:
            if manifest_path.exists():
                manifest_path.unlink()
            for config_path in (baseline_config_path, memory_config_path):
                if config_path.exists():
                    config_path.unlink()
            if db_path.exists():
                db_path.unlink()
            if db_path.with_name(f"{db_path.name}-wal").exists():
                db_path.with_name(f"{db_path.name}-wal").unlink()
            if db_path.with_name(f"{db_path.name}-shm").exists():
                db_path.with_name(f"{db_path.name}-shm").unlink()
            if campaign_root.exists():
                shutil.rmtree(campaign_root)

    def test_cli_compare_runs_supports_campaign_json_and_text(self) -> None:
        left_path = Path("test-campaign-left.campaign.json")
        right_path = Path("test-campaign-right.campaign.json")
        left_path.write_text(
            json.dumps(
                {
                    "campaign_id": "campaign-left",
                    "status": "completed",
                    "entry_count": 2,
                    "completed_entries": 2,
                    "failed_entries": 0,
                    "entries": [
                        {"name": "baseline", "command": "run", "status": "promoted", "run_id": "run-a"},
                        {"name": "memory-pass", "command": "autoresearch", "status": "promoted", "run_id": "run-b"},
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        right_path.write_text(
            json.dumps(
                {
                    "campaign_id": "campaign-right",
                    "status": "completed_with_failures",
                    "entry_count": 3,
                    "completed_entries": 2,
                    "failed_entries": 1,
                    "entries": [
                        {"name": "baseline", "command": "run", "status": "promoted", "run_id": "run-a2"},
                        {"name": "memory-pass", "command": "autoresearch", "status": "skipped", "run_id": "run-b2"},
                        {"name": "batch-pass", "command": "batch-autoresearch", "status": "failed"},
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            json_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "campaign",
                    "--left",
                    str(left_path),
                    "--right",
                    str(right_path),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(json_completed.returncode, 0, msg=json_completed.stderr)
            payload = json.loads(json_completed.stdout)
            self.assertEqual(payload["left_run_id"], "campaign-left")
            self.assertEqual(payload["right_run_id"], "campaign-right")
            self.assertEqual(payload["status_change"], {"left": "completed", "right": "completed_with_failures"})
            self.assertEqual(payload["campaign_metrics"]["entry_count"], {"left": 2, "right": 3, "delta": 1})
            self.assertEqual(payload["entry_changes"]["added"], ["batch-pass"])
            self.assertEqual(payload["entry_changes"]["retained"], ["baseline", "memory-pass"])
            self.assertEqual(
                payload["entry_result_changes"]["memory-pass"]["status_change"],
                {"left": "promoted", "right": "skipped"},
            )

            text_completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "compare-runs",
                    "--kind",
                    "campaign",
                    "--left",
                    str(left_path),
                    "--right",
                    str(right_path),
                    "--format",
                    "text",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(text_completed.returncode, 0, msg=text_completed.stderr)
            self.assertIn("Campaign metrics:", text_completed.stdout)
            self.assertIn("Added entries: batch-pass", text_completed.stdout)
            self.assertIn("Entry result changes:", text_completed.stdout)
            self.assertIn("memory-pass", text_completed.stdout)
            self.assertIn("status: promoted -> skipped", text_completed.stdout)
        finally:
            for path in (left_path, right_path):
                if path.exists():
                    path.unlink()

    def test_cli_list_campaigns_sorts_and_filters(self) -> None:
        output_dir = Path("test-output-cli-list-campaigns")
        output_dir.mkdir(exist_ok=True)
        try:
            for name, payload in [
                (
                    "campaign-a",
                    {
                        "campaign_id": "campaign-a",
                        "status": "completed",
                        "entry_count": 2,
                        "completed_entries": 2,
                        "failed_entries": 0,
                        "entries": [{"name": "baseline", "command": "run", "status": "promoted"}],
                    },
                ),
                (
                    "campaign-b",
                    {
                        "campaign_id": "campaign-b",
                        "status": "completed_with_failures",
                        "entry_count": 3,
                        "completed_entries": 2,
                        "failed_entries": 1,
                        "entries": [{"name": "baseline", "command": "run", "status": "promoted"}],
                    },
                ),
                (
                    "campaign-c",
                    {
                        "campaign_id": "campaign-c",
                        "status": "completed",
                        "entry_count": 4,
                        "completed_entries": 4,
                        "failed_entries": 0,
                        "entries": [{"name": "baseline", "command": "run", "status": "promoted"}],
                    },
                ),
            ]:
                (output_dir / f"{name}.campaign.json").write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "list-campaigns",
                    "--dir",
                    str(output_dir),
                    "--sort-by",
                    "completed_entries",
                    "--status",
                    "completed",
                    "--format",
                    "text",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("Campaigns ranked by completed_entries", completed.stdout)
            self.assertIn("1. campaign-c", completed.stdout)
            self.assertIn("2. campaign-a", completed.stdout)
            self.assertNotIn("campaign-b", completed.stdout)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_list_campaigns_skips_malformed_reports(self) -> None:
        output_dir = Path("test-output-cli-list-campaigns-malformed")
        output_dir.mkdir(exist_ok=True)
        try:
            (output_dir / "campaign-good.campaign.json").write_text(
                json.dumps(
                    {
                        "campaign_id": "campaign-good",
                        "status": "completed",
                        "entry_count": 2,
                        "completed_entries": 2,
                        "failed_entries": 0,
                        "entries": [{"name": "baseline", "command": "run", "status": "promoted"}],
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            (output_dir / "campaign-bad.campaign.json").write_text("{not json", encoding="utf-8")

            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "list-campaigns",
                    "--dir",
                    str(output_dir),
                    "--format",
                    "text",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("campaign-good", completed.stdout)
            self.assertIn("skipped malformed campaigns: 1", completed.stdout)
        finally:
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_cli_retry_campaign_reexecutes_failed_entries_only(self) -> None:
        campaign_root = Path("test-output-cli-retry-campaign")
        prior_report = campaign_root / "prior.campaign.json"
        retry_report = campaign_root / "retry.campaign.json"
        retry_manifest = campaign_root / "retry.campaign.retry-manifest.json"
        memory_config_path = Path("test-output-cli-retry-memory.json")
        db_path = campaign_root / "retry.sqlite"
        campaign_root.mkdir(exist_ok=True)
        memory_payload = json.loads(Path("examples/minimal_builtin_study.json").read_text(encoding="utf-8"))
        memory_payload["run_id"] = "retry-memory"
        memory_config_path.write_text(json.dumps(memory_payload, indent=2, sort_keys=True), encoding="utf-8")
        prior_report.write_text(
            json.dumps(
                {
                    "campaign_id": "prior-campaign",
                    "status": "completed_with_failures",
                    "entry_count": 2,
                    "completed_entries": 1,
                    "failed_entries": 1,
                    "entries": [
                        {
                            "name": "baseline",
                            "command": "run",
                            "status": "promoted",
                            "config_path": "examples/minimal_builtin_study.json",
                            "output_dir": str(campaign_root / "baseline"),
                        },
                        {
                            "name": "memory-pass",
                            "command": "autoresearch",
                            "status": "failed",
                            "config_path": str(memory_config_path),
                            "output_dir": str(campaign_root / "memory-pass"),
                            "db_path": str(db_path),
                            "memory_limit": 7,
                            "memory_quality_policy": "all",
                            "strict_quality": False,
                        },
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "retry-campaign",
                    "--campaign-report",
                    str(prior_report),
                    "--output-report",
                    str(retry_report),
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["entry_count"], 1)
            self.assertEqual(payload["completed_entries"], 1)
            self.assertEqual(payload["entry_status"], "failed")
            self.assertEqual(payload["source_campaign_report_path"], str(prior_report))
            self.assertEqual(payload["retry_manifest_path"], str(retry_manifest))
            self.assertTrue(retry_manifest.exists())
            self.assertTrue(retry_report.exists())

            retry_report_payload = json.loads(retry_report.read_text(encoding="utf-8"))
            self.assertEqual([entry["name"] for entry in retry_report_payload["entries"]], ["memory-pass"])
            self.assertNotEqual(retry_report_payload["entries"][0]["status"], "failed")
            self.assertEqual(retry_report_payload["entries"][0]["memory_limit"], 7)
            self.assertEqual(retry_report_payload["entries"][0]["memory_quality_policy"], "all")

            retry_manifest_payload = json.loads(retry_manifest.read_text(encoding="utf-8"))
            self.assertEqual(retry_manifest_payload["campaign_id"], "prior-campaign-retry-failed")
            self.assertEqual(len(retry_manifest_payload["entries"]), 1)
            self.assertEqual(retry_manifest_payload["entries"][0]["name"], "memory-pass")
        finally:
            if memory_config_path.exists():
                memory_config_path.unlink()
            if campaign_root.exists():
                shutil.rmtree(campaign_root)

    def test_cli_retry_campaign_can_include_skipped_entries_on_request(self) -> None:
        campaign_root = Path("test-output-cli-retry-skipped")
        prior_report = campaign_root / "prior.campaign.json"
        retry_report = campaign_root / "retry.campaign.json"
        campaign_root.mkdir(exist_ok=True)
        prior_report.write_text(
            json.dumps(
                {
                    "campaign_id": "prior-campaign",
                    "status": "completed",
                    "entry_count": 2,
                    "completed_entries": 2,
                    "failed_entries": 0,
                    "entries": [
                        {
                            "name": "baseline",
                            "command": "run",
                            "status": "promoted",
                            "config_path": "examples/minimal_builtin_study.json",
                            "output_dir": str(campaign_root / "baseline"),
                        },
                        {
                            "name": "retry-me",
                            "command": "run",
                            "status": "skipped",
                            "config_path": "examples/minimal_builtin_study.json",
                            "output_dir": str(campaign_root / "retry-me"),
                        },
                    ],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        try:
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "engine.app.cli",
                    "retry-campaign",
                    "--campaign-report",
                    str(prior_report),
                    "--output-report",
                    str(retry_report),
                    "--entry-status",
                    "skipped",
                ],
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["entry_count"], 1)
            self.assertEqual(payload["entry_status"], "skipped")

            retry_report_payload = json.loads(retry_report.read_text(encoding="utf-8"))
            self.assertEqual([entry["name"] for entry in retry_report_payload["entries"]], ["retry-me"])
        finally:
            if campaign_root.exists():
                shutil.rmtree(campaign_root)


if __name__ == "__main__":
    unittest.main()
