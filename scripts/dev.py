"""Small stdlib command router. All relative paths are relative to sensor-platform."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

# Support both direct script execution and import by focused workflow tests.
if __name__ == "__main__" and not __package__:
    from procedural import add_arguments, from_arguments
else:
    from scripts.procedural import add_arguments, from_arguments

ROOT = Path(__file__).resolve().parents[1]
CTEST_GROUPS = ("unit", "platform", "integration", "fusion")
PYTHON_GROUPS = {"analytics": "analytics/tests", "experiments": "experiments/tests", "workflow": "scripts/tests", "evaluation": "evaluation/tests"}


def repo_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def cache_values(build):
    cache = build / "CMakeCache.txt"
    if not cache.exists():
        return {}
    return {line.split(":", 1)[0]: line.split("=", 1)[1]
            for line in cache.read_text().splitlines()
            if not line.startswith(("#", "//")) and ":" in line and "=" in line}


def binary_dir(build, config):
    return build / config if cache_values(build).get("CMAKE_CONFIGURATION_TYPES") else build


def python_executable(override):
    if override:
        return str(repo_path(override)) if Path(override).parent != Path(".") else override
    venv = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    return str(venv) if venv.exists() else sys.executable


def supplied(args, option):
    return any(arg == option or arg.startswith(option + "=") for arg in args)


def commands(args):
    build = repo_path(args.build_dir)
    binaries = binary_dir(build, args.config)
    runtime = str(binaries / ("sensor_platform.exe" if os.name == "nt" else "sensor_platform"))
    python = python_executable(args.python)
    extra = list(getattr(args, "extra", []))
    if extra[:1] == ["--"]:
        extra.pop(0)
    if args.command == "build":
        result = []
        if args.configure or extra or not (build / "CMakeCache.txt").exists():
            result.append(["cmake", "-S", str(ROOT), "-B", str(build),
                           f"-DCMAKE_BUILD_TYPE={args.config}", *extra])
        result.append(["cmake", "--build", str(build), "--config", args.config,
                       *(["--target", args.target] if args.target else [])])
        return result
    if args.command == "test":
        if args.group in CTEST_GROUPS:
            return [["ctest", "--test-dir", str(build), "-C", args.config,
                     "--output-on-failure", "--no-tests=error", "-L", f"^{args.group}$", *extra]]
        if args.group in PYTHON_GROUPS:
            return [[python, "-m", "unittest", "discover", "-s", PYTHON_GROUPS[args.group], "-v", *extra]]
        return [[python, "tools/validate_kafka.py", "--bin-dir", str(binaries), *extra]]
    if args.command == "record":
        return [[runtime, "run", "--record", args.path, *extra]]
    if args.command == "viewer":
        viewer = str(binaries / ("sensor_platform_viewer.exe" if os.name == "nt" else "sensor_platform_viewer"))
        return [[viewer, *(["--help"] if args.viewer_help else []), *extra]]
    if args.command == "demo":
        viewer = str(binaries / ("sensor_platform_viewer.exe" if os.name == "nt" else "sensor_platform_viewer"))
        return [[python, "-m", "scripts.demo", "--runtime", runtime, "--viewer", viewer,
                 *from_arguments(args).arguments(), "--output", args.output]]
    if args.command == "replay":
        return [[runtime, "replay", args.path]]
    if args.command == "run":
        return [[runtime, "run", *extra]]
    if args.command == "fuse":
        return [[runtime, "fuse", *extra]]
    if args.command == "kafka":
        return [[str(binaries / ("sensor_platform_kafka.exe" if os.name == "nt" else "sensor_platform_kafka")), *extra]]
    if args.command == "analytics" and extra[:1] in (["export"], ["ingest"]) and not supplied(extra, "--runtime"):
        extra += ["--runtime", runtime]
    if args.command == "experiments" and extra[:1] == ["run"] and not supplied(extra, "--bin-dir"):
        extra += ["--bin-dir", str(binaries)]
    if args.command == "evaluation" and extra[:1] == ["demo"] and not supplied(extra, "--runtime"):
        extra += ["--runtime", runtime]
    return [[python, "-m", args.command, *extra]]


def parser():
    result = argparse.ArgumentParser(description=__doc__, epilog="Global options precede the command. Forwarded arguments follow it; use -- before flags if needed.")
    result.add_argument("--build-dir", default="build", help="existing or new CMake build directory (default: build)")
    result.add_argument("--config", default="Debug", help="CMake configuration (default: Debug)")
    result.add_argument("--python", help="Python interpreter for tests/data tooling (default: .venv, then current interpreter)")
    result.add_argument("--dry-run", action="store_true", help="print commands without running them")
    sub = result.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="configure if needed, then cmake --build")
    build.add_argument("--configure", action="store_true", help="refresh CMake configuration")
    build.add_argument("--target", help="build only one existing CMake target")
    build.add_argument("extra", nargs=argparse.REMAINDER, help="CMake configure arguments after --")
    test = sub.add_parser("test", help="target existing tests; default is C++ unit tests")
    test.add_argument("group", nargs="?", default="unit", choices=(*CTEST_GROUPS, *PYTHON_GROUPS, "kafka"))
    test.add_argument("extra", nargs=argparse.REMAINDER, help="CTest / unittest / validate_kafka.py arguments")
    viewer = sub.add_parser("viewer", add_help=False, help="open a recording in the graphical viewer (viewer --help for arguments)")
    viewer.add_argument("--help", dest="viewer_help", action="store_true")
    viewer.add_argument("extra", nargs=argparse.REMAINDER)
    for name, help_text in [("run", "run the local C++ sample"), ("record", "record a local run"),
                            ("demo", "run the curated recording/fusion/quality/analytics demo"),
                            ("replay", "validate/replay a recording"), ("analytics", "forward to python -m analytics"),
                            ("experiments", "forward to python -m experiments"), ("fuse", "fuse a recording or live stdin (-)"),
                            ("evaluation", "truth-separated fusion evaluation"), ("kafka", "forward to the Kafka runtime; broker must already be running")]:
        command = sub.add_parser(name, help=help_text)
        if name in ("record", "replay"):
            command.add_argument("path")
        if name == "demo":
            command.add_argument("--output", default="demo/results", help="dedicated demo results directory")
            add_arguments(command)
        elif name != "replay":
            command.add_argument("extra", nargs=argparse.REMAINDER)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    # Windows may expose both Path and PATH; MSBuild rejects duplicate environment keys.
    env = {k.upper(): v for k, v in os.environ.items()} if os.name == "nt" else os.environ.copy()
    binaries = binary_dir(repo_path(args.build_dir), args.config)
    env["SENSOR_PLATFORM_RUNTIME"] = str(binaries / ("sensor_platform.exe" if os.name == "nt" else "sensor_platform"))
    try:
        for command in commands(args):
            print("+ " + shlex.join(command), file=sys.stderr, flush=True)
            if not args.dry_run:
                subprocess.run(command, cwd=ROOT, env=env, check=True)
    except subprocess.CalledProcessError as error:
        return error.returncode
    except ValueError as error:
        print(f"dev: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"dev: {error}. Build first or check the selected tool/build paths.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
