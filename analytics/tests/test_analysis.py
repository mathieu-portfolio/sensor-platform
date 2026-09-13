"""Focused offline model validation against an explicitly built runtime."""
import os
import csv
from pathlib import Path
import subprocess
import tempfile
import unittest

from analytics.analysis import export_analysis, open_analysis
from analytics.dataset import open_dataset
from scripts.demo import ROOT, run_demo
from scripts.procedural import ProceduralConfig

RUNTIME = Path(os.environ.get("SENSOR_PLATFORM_RUNTIME", ROOT / "build/Debug/sensor_platform.exe"))


class AnalyticalModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "demo"
        run_demo(RUNTIME, self.output, self.root / "missing-viewer", ProceduralConfig(duration=4))

    def test_tables_relationships_and_truth_separation(self):
        with open_analysis(self.output / "dataset") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM runs").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM sensors").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT count(*) FROM ground_truth").fetchone()[0], 33 * 4)
            self.assertEqual(db.execute("SELECT count(*) FROM ground_truth WHERE NOT isfinite(vx) OR NOT isfinite(vy)").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(DISTINCT motion_type) FROM ground_truth").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT count(*) FROM scans s LEFT JOIN sensors n USING(run_id,sensor_id) WHERE n.sensor_id IS NULL").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM tracks t LEFT JOIN events e ON t.run_id=e.run_id AND t.source_sequence=e.stream_sequence WHERE e.run_id IS NULL").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM (SELECT run_id,run_generation,acquisition_time,track_id FROM tracks GROUP BY ALL HAVING count(*)>1)").fetchone()[0], 0)
            evaluated, samples, matched, missed = db.execute("SELECT evaluated_frames,target_samples,matched_samples,missed_target_samples FROM run_metrics").fetchone()
            self.assertEqual(evaluated, db.execute("SELECT count(DISTINCT acquisition_time_seconds) FROM scans").fetchone()[0])
            self.assertEqual(samples, evaluated * 4)
            self.assertEqual(samples, matched + missed)
        with open_dataset(self.output / "dataset/clean") as db:
            self.assertEqual({r[0] for r in db.execute("SHOW TABLES").fetchall()}, {"events", "scans", "measurements"})
        plain = self.root / "plain.events"
        subprocess.run([str(RUNTIME), "run", "--run-id", "43", "--procedural", str(self.output / "scenario.config"), "--record", str(plain)], stdout=subprocess.DEVNULL, check=True)
        self.assertEqual(plain.read_bytes(), (self.output / "recording.events").read_bytes())
        self.assertNotIn(b"truth", plain.read_bytes().lower())
        self.assertNotIn(b"target_id", plain.read_bytes())

    def test_truth_deterministic_and_layout_independent(self):
        original = (self.output / "analytical/ground_truth.csv").read_bytes()
        for seed in (73, 74):
            other = self.root / str(seed)
            run_demo(RUNTIME, other, self.root / "missing-viewer", ProceduralConfig(sensor_layout_seed=seed, duration=4))
            self.assertEqual(original, (other / "analytical/ground_truth.csv").read_bytes())

    def test_conflict_and_corruption_rejected(self):
        artifacts = self.output / "analytical"
        path = artifacts / "ground_truth.csv"
        path.write_text(path.read_text().replace(",linear", ",arc"))
        with self.assertRaisesRegex(ValueError, "different analytical"):
            export_analysis(artifacts, self.output / "tracks.jsonl", self.output / "dataset")
        partition = self.output / "dataset/analysis/run_id=43/ground_truth.parquet"
        with partition.open("ab") as stream:
            stream.write(b"corrupt")
        with self.assertRaisesRegex(ValueError, "integrity"):
            open_analysis(self.output / "dataset")

    def test_incomplete_truth_not_published(self):
        # Use a separate dataset root with the validated clean partition only.
        import shutil
        dataset = self.root / "incomplete"
        shutil.copytree(self.output / "dataset/clean", dataset / "clean")
        path = self.output / "analytical/ground_truth.csv"
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
        with self.assertRaisesRegex(ValueError, "grid mismatch"):
            export_analysis(self.output / "analytical", self.output / "tracks.jsonl", dataset)
        self.assertFalse((dataset / "analysis/run_id=43").exists())
        self.assertEqual(list((dataset / "analysis").iterdir()), [])

    def test_exposed_parameters_persist_effective_values(self):
        config = self.root / "v2.config"
        config.write_text("SENSOR_PROCEDURAL 2\n9 12 4 2 1\n10 20 2 0.5 0.8 1.2 2 3 0.7 4\n")
        artifacts = self.root / "v2"
        subprocess.run([str(RUNTIME), "run", "--run-id", "18446744073709551615",
                        "--procedural", str(config), "--analysis-output", str(artifacts)],
                       stdout=subprocess.DEVNULL, check=True)
        with (artifacts / "runs.csv").open(newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(int(row["run_id"]), 2**64-1)
        for name, value in dict(scenario_seed=9, layout_seed=12, duration_seconds=4,
                                target_count=2, sensor_count=1, speed_min=10, speed_max=20,
                                maneuver=2, convergence=.5, spawn_spread=.8, coverage=1.2,
                                layout_spread=2, noise=3, reliability=.7, clutter=4).items():
            self.assertAlmostEqual(float(row[name]), value, places=6)


if __name__ == "__main__":
    unittest.main()
