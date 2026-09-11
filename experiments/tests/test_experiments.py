import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analytics.events import parse
from experiments.config import resolve, plan
from experiments.metrics import calculate, integrity, percentile, read_events

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get("SENSOR_PLATFORM_RUNTIME", ROOT / "build/consumer-verified/Debug/sensor_platform.exe")).resolve()


def event(seq):
    return parse(f"RUN_STARTED 1 0 {seq} 0")


def trace(phase, seq, seconds):
    return dict(phase=phase, sequence=seq, wall_ns=int(seconds * 1e9))


class MetricTests(unittest.TestCase):
    def test_percentiles(self):
        self.assertIsNone(percentile([], 95))
        self.assertEqual(percentile([9], 99), 9)
        self.assertEqual(percentile([30, 0, 20, 10], 50), 15)
        self.assertAlmostEqual(percentile([30, 0, 20, 10], 95), 28.5)
        self.assertAlmostEqual(percentile([30, 0, 20, 10], 99), 29.7)
        with self.assertRaises(ValueError):
            percentile([1], 101)

    def test_backlog_and_recovery(self):
        expected = [event(1), event(2), event(3)]
        p = [trace("produced", 1, 1), trace("produced", 2, 2), trace("produced", 3, 3)]
        c = [trace("consumed", 1, 1.1), trace("pause", 1, 1.2), trace("resume", 1, 4),
             trace("consumed", 2, 4.1), trace("consumed", 3, 4.2)]
        result, latency, backlog = calculate(p, c, expected, expected)
        self.assertTrue(result["integrity_pass"])
        self.assertEqual(result["max_backlog"], 2)
        self.assertEqual(result["final_backlog"], 0)
        self.assertAlmostEqual(result["catchup_seconds"], .2)
        self.assertAlmostEqual(result["produced_events_per_second"], 1)
        self.assertAlmostEqual(result["consumed_events_per_second"], 2/3.1)
        self.assertEqual(result["latency_p50_ms"], 1200)
        self.assertEqual(len(latency), 3)
        self.assertEqual(backlog[-1][1], 0)
        incomplete, _, _ = calculate(p, c[:-1], expected, expected[:-1])
        self.assertFalse(incomplete["integrity_pass"])
        self.assertIsNone(incomplete["catchup_seconds"])
        self.assertEqual(incomplete["final_backlog"], 1)

    def test_integrity_failures_are_counted(self):
        expected = [event(1), event(2), event(3)]
        actual = [event(3), event(1), event(1), dataclasses.replace(event(1), time=2)]
        result = integrity(expected, actual)
        self.assertFalse(result["integrity_pass"])
        self.assertEqual(result["duplicate_count"], 2)
        self.assertEqual(result["conflicting_duplicate_count"], 1)
        self.assertEqual(result["missing_sequence_count"], 1)
        self.assertEqual(result["ordering_violations"], 1)
        p = [trace("produced", 1, 2)]
        c = [trace("consumed", 1, 1)]
        result, _, _ = calculate(p, c, [event(1)], [event(1)])
        self.assertEqual(result["clock_errors"], 1)
        self.assertFalse(result["integrity_pass"])
        result, _, _ = calculate([], [], [event(1)], [event(1)])
        self.assertFalse(result["trace_integrity_pass"])

    def test_configuration_is_deterministic_and_validated(self):
        config = resolve({"seed": 123, "sensor_count": 5})
        self.assertEqual(plan(config), plan(resolve(json.loads(json.dumps(config)))))
        self.assertNotEqual(plan(config), plan(resolve({"seed": 124, "sensor_count": 5})))
        for bad in [{"typo": 1}, {"sensor_count": 0}, {"scan_hz": [float("nan")]},
                    {"pause_ms": 10}, {"duration_seconds": .013},
                    {"outage": {"sensor_id": 7, "start": 0, "end": 1}}]:
            with self.subTest(config=bad), self.assertRaises(ValueError):
                resolve(bad)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def simulate(self, config):
        path = self.root / "runtime.plan"
        path.write_text(plan(config, paced=False), encoding="ascii")
        result = subprocess.run([str(RUNTIME), "run", "--experiment", str(path), "--run-id", str(config["run_id"])],
                                capture_output=True, check=True, timeout=30)
        events_path = self.root / "events"
        events_path.write_bytes(result.stdout)
        events, errors = read_events(events_path)
        self.assertFalse(errors)
        subprocess.run([str(RUNTIME), "replay", str(events_path)], stdout=subprocess.DEVNULL, check=True, timeout=30)
        return result.stdout, events

    def test_outage_continues_other_sensors_and_preserves_sequences(self):
        config = resolve({})
        baseline, base_events = self.simulate(config)
        self.assertEqual(baseline, self.simulate(config)[0])
        config["outage"] = {"sensor_id": 2, "start": .5, "end": 1.5}
        outage, events = self.simulate(config)
        self.assertEqual(outage, self.simulate(config)[0])
        scans = [e for e in events if e.kind == "MEASUREMENTS"]
        affected = [e for e in scans if e.sensor_id == 2]
        self.assertFalse(any(.5 <= e.time < 1.5 for e in affected))
        self.assertTrue(any(e.time >= 1.5 for e in affected))
        self.assertEqual([e.scan_sequence for e in affected], list(range(1, len(affected)+1)))
        self.assertEqual([e.sequence for e in events], list(range(1, len(events)+1)))
        for sensor in (1, 3):
            before = [(e.time, e.detections) for e in base_events if e.kind == "MEASUREMENTS" and e.sensor_id == sensor]
            after = [(e.time, e.detections) for e in scans if e.sensor_id == sensor]
            self.assertEqual(before, after)
        config["seed"] += 1
        self.assertNotEqual(outage, self.simulate(config)[0])

    def test_observer_rejects_truncated_stream(self):
        result = subprocess.run([str(RUNTIME), "observe"], input=b"SENSOR_EVENTS 1\nRUN_STARTED 1 0 1 0\n", capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr)

    def test_cli_pause_results_and_failed_experiment_are_saved(self):
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(dict(duration_seconds=.1, wall_seconds_per_sim_second=0,
                                               pause_after_events=2, pause_ms=10)))
        output = self.root / "result"
        command = [sys.executable, "-m", "experiments", "run", str(config_path), str(output),
                   "--bin-dir", str(RUNTIME.parent)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((output / "summary.json").read_text())
        self.assertTrue(summary["metrics"]["integrity_pass"])
        self.assertTrue(summary["metrics"]["pause_observed"])
        self.assertIsNotNone(summary["metrics"]["catchup_seconds"])
        self.assertTrue((output / "latency.csv").exists())
        # A requested pause beyond the run is a failed experiment, not a successful recovery.
        config_path.write_text(json.dumps(dict(duration_seconds=.1, wall_seconds_per_sim_second=0,
                                               pause_after_events=1000, pause_ms=10)))
        failed_output = self.root / "failed"
        command[5] = str(failed_output)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        summary = json.loads((failed_output / "summary.json").read_text())
        self.assertFalse(summary["metrics"]["integrity_pass"])
        self.assertTrue(summary["errors"])


if __name__ == "__main__":
    unittest.main()
