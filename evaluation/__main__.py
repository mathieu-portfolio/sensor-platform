import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .metrics import evaluate, load_frames
from .scenarios import generate, NAMES
from .sweep import seed, seed_list, summarize


def evaluate_scenario(name, directory, run_seed, runtime):
    generate(name, directory, run_seed)
    output = directory / "tracks.jsonl"
    env = {k.upper(): v for k, v in os.environ.items()} if os.name == "nt" else None
    subprocess.run([str(runtime.resolve()), "fuse", str(directory / "measurements.events"), "--output", str(output)], check=True, env=env)
    metrics = evaluate(load_frames(output), [json.loads(line) for line in (directory / "truth.jsonl").read_text().splitlines()])
    return dict(scenario=name, seed=run_seed, **metrics)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline fusion scenarios and truth-separated scoring")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("output", type=Path)
    demo.add_argument("--runtime", type=Path, required=True)
    demo.add_argument("--scenario", choices=NAMES)
    seeds = demo.add_mutually_exclusive_group()
    seeds.add_argument("--seed", type=seed, default=42)
    seeds.add_argument("--seeds", type=seed_list, help="comma-separated seeds; requires --scenario")
    seeds.add_argument("--seed-range", type=seed, nargs=2, metavar=("FIRST", "LAST"), help="inclusive range; requires --scenario")
    score = sub.add_parser("score")
    score.add_argument("tracks", type=Path)
    score.add_argument("truth", type=Path)
    score.add_argument("--gate", type=float, default=5)
    args = parser.parse_args(argv)
    sweep_seeds = None
    if args.command == "demo" and (args.seeds is not None or args.seed_range is not None):
        if not args.scenario:
            parser.error("--seeds/--seed-range requires --scenario")
        if args.seed_range is not None:
            first, last = args.seed_range
            if first > last:
                parser.error("seed range must be ascending (inclusive)")
            sweep_seeds = range(first, last + 1)
        else:
            sweep_seeds = args.seeds
    try:
        if args.command == "score":
            print(json.dumps(evaluate(load_frames(args.tracks), [json.loads(line) for line in args.truth.read_text().splitlines()], args.gate), indent=2))
            return 0
        args.output.mkdir(parents=True, exist_ok=False)
        if sweep_seeds is not None:
            results = [evaluate_scenario(args.scenario, args.output / f"seed-{run_seed}" / args.scenario,
                                         run_seed, args.runtime) for run_seed in sweep_seeds]
            summary = summarize(args.scenario, results)
            (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
            print(json.dumps(summary, indent=2, allow_nan=False))
            return 0
        summaries = []
        for name in [args.scenario] if args.scenario else NAMES:
            summaries.append(evaluate_scenario(name, args.output / name, args.seed, args.runtime))
        (args.output / "evaluation.json").write_text(json.dumps(summaries, indent=2) + "\n")
        print(json.dumps(summaries, indent=2))
        return 0
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"evaluation: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
