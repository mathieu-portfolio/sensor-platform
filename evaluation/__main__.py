import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .metrics import evaluate, load_frames
from .scenarios import generate, NAMES


def main():
    parser = argparse.ArgumentParser(description="Offline fusion scenarios and truth-separated scoring")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("output", type=Path)
    demo.add_argument("--runtime", type=Path, required=True)
    demo.add_argument("--scenario", choices=NAMES)
    demo.add_argument("--seed", type=int, default=42)
    score = sub.add_parser("score")
    score.add_argument("tracks", type=Path)
    score.add_argument("truth", type=Path)
    score.add_argument("--gate", type=float, default=5)
    args = parser.parse_args()
    try:
        if args.command == "score":
            print(json.dumps(evaluate(load_frames(args.tracks), [json.loads(line) for line in args.truth.read_text().splitlines()], args.gate), indent=2))
            return 0
        if not 0 <= args.seed <= 2**32 - 4:
            raise ValueError("seed must be in 0..4294967292")
        args.output.mkdir(parents=True, exist_ok=False)
        summaries = []
        env = {k.upper(): v for k, v in os.environ.items()} if os.name == "nt" else None
        for name in [args.scenario] if args.scenario else NAMES:
            directory = args.output / name
            generate(name, directory, args.seed)
            output = directory / "tracks.jsonl"
            subprocess.run([str(args.runtime.resolve()), "fuse", str(directory / "measurements.events"), "--output", str(output)], check=True, env=env)
            metrics = evaluate(load_frames(output), [json.loads(line) for line in (directory / "truth.jsonl").read_text().splitlines()])
            summaries.append(dict(scenario=name, seed=args.seed, **metrics))
        (args.output / "evaluation.json").write_text(json.dumps(summaries, indent=2) + "\n")
        print(json.dumps(summaries, indent=2))
        return 0
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"evaluation: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
