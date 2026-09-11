import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from evaluation.scenarios import generate, NAMES
from evaluation.metrics import evaluate, load_frames

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get("SENSOR_PLATFORM_RUNTIME", ROOT / "build/consumer-verified/Debug/sensor_platform.exe")).resolve()


class FusionEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self, name):
        directory = self.root / name
        generate(name, directory)
        source = directory / "measurements.events"
        result = subprocess.run([str(RUNTIME), "fuse", str(source)], capture_output=True, check=True)
        tracks = directory / "tracks.jsonl"
        tracks.write_bytes(result.stdout)
        return directory, result.stdout, load_frames(tracks)

    def test_deterministic_scenarios_and_recording_stream_equivalence(self):
        for name in NAMES:
            with self.subTest(name=name):
                directory, expected, frames = self.fixture(name)
                second = self.root / (name + "-repeat")
                generate(name, second)
                source = (directory / "measurements.events").read_bytes()
                self.assertEqual(source, (second / "measurements.events").read_bytes())
                actual = subprocess.run([str(RUNTIME), "fuse", "-"], input=source, capture_output=True, check=True).stdout
                self.assertEqual(actual, expected)
                metrics = evaluate(frames, [json.loads(line) for line in (directory / "truth.jsonl").read_text().splitlines()])
                self.assertEqual(metrics["id_switches"], 2 if name == "crossing" else 0)
                self.assertLess(metrics["position_rmse"], 1)
                self.assertEqual(metrics["missed_target_samples"], 2 if name == "crossing" else 1)
                self.assertEqual(metrics["unique_false_tracks"], 1 if name == "outage_noise" else 0)
                self.assertNotIn(b"truth_id", expected)
                self.assertNotIn(b"entity_id", expected)
                self.assertTrue(any(len(t["sensors"]) > 1 for f in frames for t in f["tracks"]))

    def test_noise_seed_and_outage_gap(self):
        directory, _, frames = self.fixture("outage_noise")
        generate("outage_noise", self.root / "other", seed=43)
        self.assertNotEqual((directory / "measurements.events").read_bytes(), (self.root / "other/measurements.events").read_bytes())
        for f in frames:
            if 2 <= f["acquisition_time"] < 5:
                self.assertFalse(any(a["sensor_id"] == 2 for a in f["associations"]))
        self.assertTrue(any(f["retired"] for f in frames))

    def test_invalid_recording_never_overwrites_output_and_live_prefix_fails(self):
        source, target = self.root / "bad.events", self.root / "tracks"
        source.write_text("SENSOR_EVENTS 1\nRUN_STARTED 7 0 1 0\n")
        target.write_text("preserve")
        result = subprocess.run([str(RUNTIME), "fuse", str(source), "--output", str(target)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "preserve")
        self.assertEqual(result.stdout, b"")
        result = subprocess.run([str(RUNTIME), "fuse", "-"], input=source.read_bytes(), capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stdout)  # Live output is a prefix, not falsely advertised as complete.
        target.write_bytes(result.stdout)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            load_frames(target)

    def test_metric_definitions_and_truth_reset_identity(self):
        def frame(seq, gen, track_id):
            return dict(run_id=1, run_generation=gen, source_sequence=seq, acquisition_time=0,
                        tracks=[dict(track_id=track_id, state="confirmed", x=3, y=4),
                                dict(track_id=99, state="coasting", x=100, y=100)])
        def truth(seq, gen):
            return dict(run_id=1, run_generation=gen, source_sequence=seq, acquisition_time=0,
                        entities=[dict(truth_id="A", x=0, y=0), dict(truth_id="B", x=-100, y=-100)])
        result = evaluate([frame(1, 0, 1), frame(2, 0, 2), frame(3, 1, 3)],
                          [truth(1, 0), truth(2, 0), truth(3, 1)], gate=5)
        self.assertEqual(result["position_rmse"], 5)
        self.assertEqual(result["missed_target_samples"], 3)
        self.assertEqual(result["false_track_samples"], 3)
        self.assertEqual(result["id_switches"], 1)
        with self.assertRaisesRegex(ValueError, "duplicate truth"):
            evaluate([frame(1, 0, 1)], [truth(1, 0), truth(1, 0)])


if __name__ == "__main__":
    unittest.main()
