import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("dev", Path(__file__).resolve().parents[1] / "dev.py")
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)


class DeveloperWorkflowTests(unittest.TestCase):
    def test_viewer_routes_selected_build_and_forwards_arguments(self):
        with tempfile.TemporaryDirectory(prefix="viewer build ") as directory:
            build = Path(directory)
            for multi_config in (False, True):
                if multi_config:
                    (build / "CMakeCache.txt").write_text("CMAKE_CONFIGURATION_TYPES:STRING=Debug;Release\n")
                binary = (build / "Release" if multi_config else build) / (
                    "sensor_platform_viewer.exe" if dev.os.name == "nt" else "sensor_platform_viewer")
                for extra in (["demo/results/recording.events", "--layout", "demo/results/sensors.layout",
                               "--frames", "2", "--screenshot", "image with spaces.png"], ["--help"], ["--", "--help"]):
                    with self.subTest(multi_config=multi_config, extra=extra):
                        with patch.object(dev.subprocess, "run") as execute:
                            self.assertEqual(dev.main(["--build-dir", directory, "--config", "Release", "viewer", *extra]), 0)
                        execute.assert_called_once()
                        self.assertEqual(execute.call_args.args[0], [str(binary), *(extra[1:] if extra[0] == "--" else extra)])
                        self.assertEqual(execute.call_args.kwargs["cwd"], dev.ROOT)

    def test_binary_layout_and_explicit_runtime_override(self):
        with tempfile.TemporaryDirectory(prefix="dev build ") as directory:
            build = Path(directory)
            self.assertEqual(dev.binary_dir(build, "Debug"), build)
            (build / "CMakeCache.txt").write_text("CMAKE_CONFIGURATION_TYPES:STRING=Debug;Release\n")
            self.assertEqual(dev.binary_dir(build, "Release"), build / "Release")
            args = dev.parser().parse_args(["--build-dir", directory, "analytics", "export", "in.events", "data"])
            self.assertIn(str(build / "Debug" / ("sensor_platform.exe" if dev.os.name == "nt" else "sensor_platform")), dev.commands(args)[0])
            args = dev.parser().parse_args(["analytics", "export", "in.events", "data", "--runtime=custom"])
            self.assertNotIn("--runtime", dev.commands(args)[0])

    def test_filters_forward_without_implicit_build_or_kafka(self):
        for argv, needle in [(["test", "unit", "-R", "events"], "ctest"),
                              (["test", "experiments", "-k", "percentiles"], "unittest"),
                              (["kafka", "consumer", "--topic", "one", "--group", "viewer"], "consumer")]:
            command = dev.commands(dev.parser().parse_args(argv))
            self.assertEqual(len(command), 1)
            self.assertIn(needle, command[0])
            self.assertEqual(command[0][-2:], argv[-2:])
        default = dev.commands(dev.parser().parse_args(["test"]))[0]
        self.assertIn("^unit$", default)
        self.assertIn("--no-tests=error", default)

    def test_ingestion_receives_runtime_unless_explicitly_overridden(self):
        args = dev.parser().parse_args(["analytics", "ingest", "inbox", "data"])
        command = dev.commands(args)[0]
        self.assertIn("--runtime", command)
        self.assertEqual(command[command.index("ingest")+1:command.index("--runtime")], ["inbox", "data"])
        args = dev.parser().parse_args(["analytics", "ingest", "inbox", "data", "--runtime", "custom"])
        command = dev.commands(args)[0]
        self.assertEqual(command.count("--runtime"), 1)
        self.assertEqual(command[-1], "custom")

    def test_configure_only_when_requested_or_cache_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ["--build-dir", directory, "build", "--target", "sensor_platform"]
            self.assertEqual(len(dev.commands(dev.parser().parse_args(argv))), 2)
            (Path(directory) / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=Debug\n")
            self.assertEqual(len(dev.commands(dev.parser().parse_args(argv))), 1)
            command = dev.commands(dev.parser().parse_args(argv + ["--", "-DSENSOR_PLATFORM_KAFKA=ON"]))
            self.assertIn("-DSENSOR_PLATFORM_KAFKA=ON", command[0])

    def test_failure_stops_following_steps_and_dry_run_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ["--build-dir", directory, "build"]
            with patch.object(dev.subprocess, "run", side_effect=subprocess.CalledProcessError(7, "cmake")) as execute:
                self.assertEqual(dev.main(argv), 7)
                self.assertEqual(execute.call_count, 1)
                self.assertEqual(execute.call_args.kwargs["cwd"], dev.ROOT)
            with patch.object(dev.subprocess, "run") as execute:
                self.assertEqual(dev.main(["--dry-run", *argv]), 0)
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
