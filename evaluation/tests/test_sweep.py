import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluation.__main__ import main
from evaluation.sweep import METRICS, MAX_SEED, summarize


def result(seed, value):
    return dict(seed=seed, **dict.fromkeys(METRICS, value))


class SeedSweepTests(unittest.TestCase):
    def test_deterministic_aggregation_and_null_rmse(self):
        rows = [result(3, 4), result(1, 2), result(2, 3)]
        first = summarize("outage_noise", rows)
        self.assertEqual(first, summarize("outage_noise", list(reversed(rows))))
        self.assertEqual(first["seeds"], [1, 2, 3])
        self.assertEqual(first["aggregate"]["position_rmse"], dict(valid_seeds=3, mean=3, min=2, max=4))
        rows[0]["position_rmse"] = None
        self.assertEqual(summarize("outage_noise", rows)["aggregate"]["position_rmse"],
                         dict(valid_seeds=2, mean=2.5, min=2, max=3))
        for row in rows:
            row["position_rmse"] = None
        self.assertEqual(summarize("outage_noise", rows)["aggregate"]["position_rmse"],
                         dict(valid_seeds=0, mean=None, min=None, max=None))
        for bad in ([], [result(1, 0), result(1, 0)]):
            with self.assertRaises(ValueError):
                summarize("overlap", bad)

    def test_list_and_inclusive_range_route_identical_configs(self):
        with tempfile.TemporaryDirectory() as directory:
            summaries = []
            for index, flags in enumerate((["--seeds", "3,1,2"], ["--seed-range", "1", "3"])):
                output = Path(directory) / str(index)
                with patch("evaluation.__main__.evaluate_scenario", side_effect=lambda name, path, seed, runtime: result(seed, seed)) as evaluate, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["demo", str(output), "--runtime", "runtime", "--scenario", "overlap", *flags]), 0)
                    self.assertEqual([c.args[2] for c in evaluate.call_args_list], [1, 2, 3])
                    self.assertEqual(evaluate.call_args_list[0].args[1], output / "seed-1/overlap")
                summaries.append((output / "summary.json").read_bytes())
            self.assertEqual(*summaries)

    def test_invalid_arguments_fail_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            for flags in (["--seeds", "1,1"], ["--seeds", "1,"], ["--seeds", "-1"],
                          ["--seed-range", "4", "2"], ["--seed-range", "0", str(MAX_SEED+1)],
                          ["--seed", "42", "--seeds", "1"], ["--seeds", "1.5"]):
                with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main(["demo", str(output), "--runtime", "runtime", "--scenario", "overlap", *flags])
                self.assertEqual(error.exception.code, 2)
                self.assertFalse(output.exists())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["demo", str(output), "--runtime", "runtime", "--seeds", "1"])
            self.assertFalse(output.exists())

    def test_single_seed_demo_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo"
            with patch("evaluation.__main__.evaluate_scenario", return_value=result(MAX_SEED, 0)) as evaluate, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["demo", str(output), "--runtime", "runtime", "--scenario", "crossing", "--seed", str(MAX_SEED)]), 0)
                self.assertEqual(evaluate.call_args.args, ("crossing", output / "crossing", MAX_SEED, Path("runtime")))
            self.assertEqual(json.loads((output / "evaluation.json").read_text()), [result(MAX_SEED, 0)])
            self.assertFalse((output / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
