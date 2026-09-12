"""Focused orchestration tests using the explicitly selected, already-built runtime."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import demo, dev
from scripts.procedural import ProceduralConfig

RUNTIME = Path(os.environ.get("SENSOR_PLATFORM_RUNTIME", demo.ROOT / "build/consumer-verified/Debug/sensor_platform.exe"))


class DemoWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="platform demo ")
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "results with spaces"
        self.viewer = Path(temporary.name) / "missing viewer.exe"

    def test_single_command_routes_selected_tools_and_output(self):
        args = dev.parser().parse_args(["--build-dir", "build/consumer-verified", "demo", "--output", "demo/results"])
        command = dev.commands(args)[0]
        self.assertEqual(command[1:3], ["-m", "scripts.demo"])
        self.assertIn("--runtime", command)
        self.assertIn("--viewer", command)
        self.assertEqual(command[-2:], ["--output", "demo/results"])
        with patch.object(dev.subprocess, "run") as execute:
            self.assertEqual(dev.main(["--dry-run", "demo"]), 0)
            execute.assert_not_called()

    def test_end_to_end_artifacts_and_idempotent_repeat(self):
        # Preserve the previous curated run in the same immutable dataset while
        # ensuring current reports do not accidentally include its scan counts.
        from analytics.ingestion import ingest
        self.output.mkdir()
        legacy = self.output / "legacy.events"
        subprocess.run([str(RUNTIME), "run", "--run-id", "42", "--record", str(legacy)],
                       stdout=subprocess.DEVNULL, check=True)
        ingest(legacy, self.output / "dataset", RUNTIME)
        first = demo.run_demo(RUNTIME, self.output, self.viewer)
        self.assertEqual(first["status"], "passed")
        self.assertEqual(first["runs"][0]["last_event_time_seconds"], 20.0)
        self.assertEqual([run["run_id"] for run in first["runs"]], [demo.RUN_ID])
        self.assertEqual([sensor["scans"] for sensor in first["sensors"]], [81, 21, 41])
        self.assertEqual(first["counts"]["events"], 148)
        self.assertEqual(first["counts"]["scans"], 143)
        self.assertGreater(first["counts"]["measurements"], 400)
        self.assertEqual(first["ingestion"]["status"], "imported")
        self.assertEqual(first["ingestion"]["quality_status"], "passed")
        self.assertIn("clean_reconciliation", first["ingestion"]["checks_passed"])
        self.assertEqual(first["replay"]["status"], "matched")
        self.assertEqual(first["fusion"]["snapshots"], 148)
        self.assertEqual(first["fusion"]["associations"], first["counts"]["measurements"])
        self.assertGreaterEqual(first["fusion"]["final_active_tracks"], 3)
        self.assertEqual(first["system"]["production_marks"], 148)
        self.assertFalse(first["viewer"]["available"])
        for name in ("recording.events", "replayed.events", "tracks.jsonl", "production.csv", "ingestion.json",
                     "runs.csv", "sensors.csv", "fusion.csv", "scenario.config", "sensors.layout", "viewer.md", "workflow.log", "summary.json"):
            self.assertTrue((self.output / name).is_file(), name)
        self.assertEqual((self.output / "scenario.config").read_text(), ProceduralConfig().text())
        geometry = (self.output / "sensors.layout").read_bytes()
        self.assertNotEqual(geometry, (demo.ROOT / "docs/sample.sensors.layout").read_bytes())
        before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in (self.output / "dataset").rglob("*") if path.is_file()}
        recording = (self.output / "recording.events").read_bytes()
        tracks = (self.output / "tracks.jsonl").read_bytes()
        second = demo.run_demo(RUNTIME, self.output, self.viewer)
        self.assertEqual(second["ingestion"]["status"], "unchanged")
        self.assertEqual(second["counts"], first["counts"])
        self.assertEqual(second["fusion"], first["fusion"])
        self.assertEqual((self.output / "recording.events").read_bytes(), recording)
        self.assertEqual((self.output / "tracks.jsonl").read_bytes(), tracks)
        self.assertEqual((self.output / "sensors.layout").read_bytes(), geometry)
        self.assertEqual({str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                          for path in (self.output / "dataset").rglob("*") if path.is_file()}, before)

    def test_cli_parameters_and_independent_layout(self):
        args = dev.parser().parse_args(["demo", "--scenario-seed", "9", "--sensor-layout-seed", "12",
                                       "--duration", "8", "--target-count", "5", "--sensor-count", "4"])
        command = dev.commands(args)[0]
        self.assertIn("--scenario-seed", command)
        self.assertEqual(command[command.index("--sensor-layout-seed")+1], "12")
        config = ProceduralConfig(9, 12, 8, 5, 4)
        first = demo.run_demo(RUNTIME, self.output, self.viewer, config)
        self.assertEqual(first["runs"][0]["last_event_time_seconds"], 8)
        self.assertEqual(len(first["sensors"]), 4)
        self.assertEqual(first["procedural_config"]["target_count"], 5)
        geometry = (self.output / "sensors.layout").read_bytes()
        other = self.output.parent / "other"
        demo.run_demo(RUNTIME, other, self.viewer, ProceduralConfig(10, 12, 8, 5, 4))
        self.assertEqual((other / "sensors.layout").read_bytes(), geometry)
        self.assertNotEqual((other / "recording.events").read_bytes(), (self.output / "recording.events").read_bytes())

    def test_invalid_configuration_rejected_before_subprocess(self):
        for values in (dict(duration=0), dict(target_count=13), dict(sensor_count=0),
                       dict(scenario_seed=-1), dict(sensor_layout_seed=2**32)):
            with self.assertRaises(ValueError):
                ProceduralConfig(**values)
        config = self.output.parent / "invalid.config"
        config.write_text("SENSOR_PROCEDURAL 1\n1 2 20 0 3\n")
        result = subprocess.run([str(RUNTIME), "run", "--procedural", str(config)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        config.write_text(ProceduralConfig().text())
        for conflicting in (["--sample-seconds", "20"], ["--experiment", "missing.plan"]):
            result = subprocess.run([str(RUNTIME), "run", "--procedural", str(config), *conflicting], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")

    def test_subprocess_failure_replaces_stale_success_and_stops_pipeline(self):
        self.output.mkdir()
        (self.output / "summary.json").write_text('{"status":"passed"}')
        with patch.object(demo.subprocess, "run", side_effect=subprocess.CalledProcessError(7, "record")) as execute, \
             patch("analytics.ingestion.ingest") as ingestion:
            with self.assertRaises(subprocess.CalledProcessError):
                demo.run_demo(RUNTIME, self.output, self.viewer)
            self.assertEqual(execute.call_count, 1)
            ingestion.assert_not_called()
        report = json.loads((self.output / "summary.json").read_text())
        self.assertEqual((report["status"], report["stage"]), ("failed", "record"))
        self.assertEqual(report["error_type"], "CalledProcessError")

    def test_quality_failure_prevents_summary_success_and_viewer_preparation(self):
        with patch("analytics.ingestion.ingest", side_effect=ValueError("quality rejected")):
            with self.assertRaisesRegex(ValueError, "quality rejected"):
                demo.run_demo(RUNTIME, self.output, self.viewer)
        report = json.loads((self.output / "summary.json").read_text())
        self.assertEqual((report["status"], report["stage"]), ("failed", "ingestion"))
        self.assertTrue((self.output / "recording.events").exists())
        self.assertFalse((self.output / "viewer.md").exists())

    def test_missing_runtime_records_preflight_failure(self):
        with self.assertRaisesRegex(FileNotFoundError, "Build sensor_platform first"):
            demo.run_demo(self.output / "missing", self.output, self.viewer)
        report = json.loads((self.output / "summary.json").read_text())
        self.assertEqual((report["status"], report["stage"]), ("failed", "preflight"))


if __name__ == "__main__":
    unittest.main()
