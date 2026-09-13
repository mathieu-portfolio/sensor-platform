"""Focused procedural sweep planning, collection, and reproducibility tests."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from experiments.sweep import PARAMETERS, SweepConfig, resolve, run_sweep
from scripts import dev

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get("SENSOR_PLATFORM_RUNTIME", ROOT / "build/Debug/sensor_platform.exe"))
SPEC = dict(version=1, name="test-quality", seeds=[9, 10],
            fixed=dict(duration=4, target_count=2, sensor_count=1, sensor_layout_seed=73),
            vary=dict(noise=[0, 2]))


class SweepPlanningTests(unittest.TestCase):
    def test_cartesian_grid_seed_range_order_and_defaults(self):
        spec = deepcopy(SPEC)
        spec["vary"]["reliability"] = [.5, 1]
        normalized, runs = resolve(spec)
        self.assertEqual(len(runs), 2 * 2 * 2)
        self.assertEqual(len({i for i, _ in runs}), 8)
        self.assertTrue(all(0 < i < 2**64 for i, _ in runs))
        self.assertEqual(normalized["fixed"]["coverage"], 1)
        reordered = deepcopy(spec)
        reordered["seeds"] = dict(start=9, stop=11)
        reordered["vary"] = dict(reliability=[1, .5], noise=[2, 0])
        self.assertEqual(resolve(reordered), (normalized, runs))
        for _, config in runs:
            self.assertEqual(config.sensor_layout_seed, 73)
            self.assertEqual(config.text().splitlines()[0], "SENSOR_PROCEDURAL 2")
        self.assertEqual(list(asdict(SweepConfig()))[-10:], list(PARAMETERS))

    def test_all_exposed_variables_and_validation_before_execution(self):
        values = dict(noise=2, reliability=.5, clutter=3, target_count=3, sensor_count=2,
                      maneuver=2, convergence=.5, coverage=1.2, layout_spread=2)
        spec = deepcopy(SPEC)
        spec["fixed"] = dict(duration=4)
        spec["vary"] = {k: [v] for k, v in values.items()}
        for _, config in resolve(spec)[1]:
            for key, value in values.items():
                self.assertEqual(getattr(config, key), value)
        bad_specs = []
        for change in [dict(seeds=[]), dict(seeds=[True]), dict(seeds=[1, 1]),
                       dict(seeds={"start": 0, "stop": 2, "step": 0}),
                       dict(vary={}), dict(vary={"noise": [1, 1]}),
                       dict(vary={"noise": [float("nan")]}), dict(vary={"noise": [6]}),
                       dict(vary={"sensor_count": [1.5]}), dict(vary={"unknown": [1]}),
                       dict(fixed={"noise": 0}), dict(fixed={"scenario_seed": 1}),
                       dict(fixed={"speed_min": 20, "speed_max": 10}),
                       dict(seeds={"start": 0, "stop": 4097})]:
            bad_specs.append(dict(deepcopy(SPEC), **change))
        with tempfile.TemporaryDirectory() as temporary, patch("experiments.sweep.subprocess.run") as execute:
            output = Path(temporary) / "never-created"
            for spec in bad_specs:
                with self.subTest(spec=spec), self.assertRaises(ValueError):
                    run_sweep(spec, output, RUNTIME)
                self.assertFalse(output.exists())
            execute.assert_not_called()

    def test_developer_command_routes_build_python_and_spec(self):
        command = dev.commands(dev.parser().parse_args([
            "--build-dir", "build", "--python", "custom-python", "sweep",
            "--spec", "spec with spaces.json", "--output", "data/test sweep"]))[0]
        self.assertEqual(command[:3], ["custom-python", "-m", "experiments.sweep"])
        self.assertIn("sensor_platform", command[4])
        self.assertEqual(command[-4:], ["--spec", "spec with spaces.json", "--output", "data/test sweep"])

    def test_failure_does_not_publish_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "failed"
            with patch("experiments.sweep.subprocess.run", side_effect=RuntimeError("simulation failed")):
                with self.assertRaisesRegex(RuntimeError, "simulation failed"):
                    run_sweep(SPEC, output, RUNTIME)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])
            output.mkdir()
            sentinel = output / "keep"
            sentinel.write_text("original")
            with self.assertRaises(FileExistsError):
                run_sweep(SPEC, output, RUNTIME)
            self.assertEqual(sentinel.read_text(), "original")


class SweepDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.first, cls.second = cls.root / "first", cls.root / "second"
        cls.manifest = run_sweep(SPEC, cls.first, RUNTIME)
        run_sweep(SPEC, cls.second, RUNTIME)

    def test_deterministic_per_run_artifacts_and_tables(self):
        self.assertEqual(self.manifest["run_count"], 4)
        # Includes raw/clean/analytical Parquet, truth CSV, event recordings,
        # tracks, experiment tables and manifests; no wall-clock observations.
        first = {str(p.relative_to(self.first)): p.read_bytes() for p in self.first.rglob("*") if p.is_file()}
        second = {str(p.relative_to(self.second)): p.read_bytes() for p in self.second.rglob("*") if p.is_file()}
        self.assertEqual(first, second)

    def test_duckdb_metadata_metrics_and_individual_run_relationships(self):
        with duckdb.connect() as db:
            db.read_parquet(str(self.first / "experiments.parquet")).create_view("experiments")
            db.read_parquet(str(self.first / "experiment_metrics.parquet")).create_view("metrics")
            rows = db.execute("SELECT run_id,seed,scenario_seed,layout_seed,noise,requested_config,target_count,sensor_count FROM experiments ORDER BY run_id").fetchall()
            self.assertEqual(len(rows), 4)
            expected = dict(resolve(SPEC)[1])
            for run_id, seed, scenario_seed, layout_seed, noise, config, targets, sensors in rows:
                self.assertEqual(json.loads(config), asdict(expected[run_id]))
                self.assertEqual((seed, scenario_seed, layout_seed, noise, targets, sensors),
                                 (expected[run_id].scenario_seed, expected[run_id].scenario_seed, 73, expected[run_id].noise, 2, 1))
                directory = self.first / "runs" / f"run_id={run_id}"
                self.assertTrue((directory / "analytical/ground_truth.csv").is_file())
                self.assertNotIn("truth", (directory / "recording.events").read_text().lower())
            self.assertEqual(db.execute("SELECT count(*) FROM experiments JOIN metrics USING(run_id,experiment_id,seed)").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT count(*) FROM metrics WHERE matched_samples+missed_target_samples != target_samples OR measurement_count < 0 OR abs(measurements_per_second * 4 - measurement_count)>1e-9").fetchone()[0], 0)
            db.read_parquet(str(self.first / "dataset/analysis/run_id=*/run_metrics.parquet"), hive_partitioning=False).create_view("run_metrics")
            self.assertEqual(db.execute("SELECT count(*) FROM metrics m JOIN run_metrics r USING(run_id) WHERE m.position_rmse IS DISTINCT FROM r.position_rmse OR m.id_switches != r.id_switches OR m.false_track_samples != r.false_track_samples").fetchone()[0], 0)
            db.read_parquet(str(self.first / "dataset/clean/run_id=*/scans.parquet"), hive_partitioning=False).create_view("scans")
            self.assertEqual(db.execute("SELECT sum(scan_count),sum(measurement_count) FROM metrics").fetchone(),
                             db.execute("SELECT count(*),sum(measurement_count) FROM scans").fetchone())
            self.assertEqual(len(db.execute("SELECT noise,avg(position_rmse) FROM experiments JOIN metrics USING(run_id) GROUP BY noise").fetchall()), 2)


if __name__ == "__main__":
    unittest.main()
