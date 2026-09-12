"""Focused orchestration tests using the explicitly selected, already-built runtime."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import demo, dev

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
        first = demo.run_demo(RUNTIME, self.output, self.viewer)
        self.assertEqual(first["status"], "passed")
        self.assertEqual(first["counts"], dict(events=15, scans=10, measurements=11))
        self.assertEqual(first["ingestion"]["status"], "imported")
        self.assertEqual(first["ingestion"]["quality_status"], "passed")
        self.assertIn("clean_reconciliation", first["ingestion"]["checks_passed"])
        self.assertEqual(first["replay"]["status"], "matched")
        self.assertEqual(first["fusion"]["snapshots"], 15)
        self.assertEqual(first["fusion"]["associations"], 11)
        self.assertEqual(first["fusion"]["final_active_tracks"], 2)
        self.assertEqual(first["system"]["production_marks"], 15)
        self.assertFalse(first["viewer"]["available"])
        for name in ("recording.events", "replayed.events", "tracks.jsonl", "production.csv", "ingestion.json",
                     "runs.csv", "sensors.csv", "fusion.csv", "sensors.layout", "viewer.md", "workflow.log", "summary.json"):
            self.assertTrue((self.output / name).is_file(), name)
        self.assertEqual((self.output / "sensors.layout").read_bytes(), (demo.ROOT / "docs/sample.sensors.layout").read_bytes())
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
        self.assertEqual({str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                          for path in (self.output / "dataset").rglob("*") if path.is_file()}, before)

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
