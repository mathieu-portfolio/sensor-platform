"""The curated five-dimension study; generation and persisted-only analysis are separate."""
import argparse
import json
from pathlib import Path
import sys
import time

import duckdb

from analytics.canonical import analyze, NOTES
from analytics.dataset import digest
from analytics.publication import staging_directory
from experiments.sweep import resolve, identity, run_sweep

DIMENSIONS = {
    'noise': ('noise', 'Sensor noise', 'Noise multiplier', ['position_rmse', 'missed_target_samples', 'id_switches']),
    'reliability': ('reliability', 'Detection reliability', 'Reliability multiplier', ['measurement_count', 'position_rmse', 'missed_target_samples']),
    'clutter': ('clutter', 'Clutter', 'Clutter multiplier', ['false_track_samples', 'position_rmse']),
    'convergence': ('convergence', 'Target convergence', 'Convergence', ['id_switches', 'position_rmse', 'false_track_samples']),
    'sensor_network': ('sensor_count', 'Sensor network', 'Sensor count', ['position_rmse', 'measurement_count']),
}
LABELS = {'position_rmse': 'Tracking RMSE', 'missed_target_samples': 'Missed target samples',
          'id_switches': 'ID switches', 'measurement_count': 'Measurement yield', 'false_track_samples': 'False track samples'}


def plan(definition):
    if not isinstance(definition, dict) or set(definition) != {'version', 'name', 'question', 'seeds', 'fixed', 'dimensions'}:
        raise ValueError('expected version, name, question, seeds, fixed, dimensions')
    if type(definition['version']) is not int or definition['version'] != 1 or any(not isinstance(definition[k], str) or not definition[k].strip() or any(ord(c)<32 or ord(c)>126 for c in definition[k]) for k in ('name', 'question')):
        raise ValueError('expected version 1 and single-line name/question')
    if not isinstance(definition['dimensions'], dict) or set(definition['dimensions']) != set(DIMENSIONS):
        raise ValueError('study requires exactly the five curated dimensions')
    specs = {}
    for name, (parameter, _, _, _) in DIMENSIONS.items():
        varying = definition['dimensions'][name]
        if not isinstance(varying, dict) or set(varying) != {parameter} or not 2 <= len(varying[parameter]) <= 5:
            raise ValueError(f'{name} requires 2..5 values for {parameter}')
        spec, _ = resolve(dict(version=1, name=definition['name'] + ' / ' + name,
                               seeds=definition['seeds'], fixed=definition['fixed'], vary=varying))
        specs[name] = spec
    return specs


def generate(definition, output, runtime):
    specs = plan(definition)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    (output / 'definition.json').write_text(json.dumps(definition, indent=2, sort_keys=True) + '\n')
    try:
        for name, spec in specs.items():
            run_sweep(spec, output / 'sweeps' / name, runtime)
        summary = analyze_study(output)
        elapsed = round(time.perf_counter() - started, 3)
        (output / 'execution.json').write_text(json.dumps(dict(status='complete', elapsed_seconds=elapsed,
            run_count=summary['run_count'], timing_scope='sequential generation, ingestion, evaluation and study analysis'), indent=2) + '\n')
        return dict(run_count=summary['run_count'], elapsed_seconds=elapsed, output=str(output))
    except Exception as error:
        (output / 'execution.json').write_text(json.dumps(dict(status='failed', elapsed_seconds=round(time.perf_counter()-started, 3), error=str(error)), indent=2) + '\n')
        raise


def phrase(rows):
    """Describe all levels, never infer significance or smooth a trend."""
    means = [r['mean'] for r in rows]
    text = LABELS[rows[0]['metric']] + ': ' + ' / '.join('no matches' if v is None else f'{v:.3f}' for v in means) + ' ' + rows[0]['unit']
    if all(v is not None for v in means):
        differences = [b-a for a, b in zip(means, means[1:])]
        if any(d > 0 for d in differences) and any(d < 0 for d in differences):
            text += ' (non-monotonic means)'
    return text


def analyze_study(source, output=None):
    source = Path(source).resolve()
    definition = json.loads((source / 'definition.json').read_text())
    specs = plan(definition)
    output = Path(output).resolve() if output else source / 'analysis'
    if output.exists():
        raise FileExistsError(f'analysis already exists: {output}; choose a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with staging_directory(output.parent) as staging:
        panels, manifests, all_ids = [], {}, set()
        total = 0
        for name, spec in specs.items():
            sweep = source / 'sweeps' / name
            manifest = json.loads((sweep / 'manifest.json').read_text())
            if manifest['experiment_id'] != identity(spec):
                raise ValueError('study definition / sweep identity mismatch')
            result = analyze(sweep, staging / name)
            manifests[name] = dict(experiment_id=manifest['experiment_id'], source_files=result['source_files'],
                                   runtime_sha256=manifest['runtime_sha256'], sql_sha256=result['sql_sha256'])
            parameter, title, axis, metrics = DIMENSIONS[name]
            with duckdb.connect() as db:
                db.read_parquet(str(staging / name / (name + '.parquet'))).create_view('stats')
                records = db.execute(f'SELECT *, {parameter} AS value FROM stats ORDER BY {parameter},metric')
                cols = [c[0] for c in records.description]
                rows = [dict(zip(cols, r)) for r in records.fetchall()]
                expected_ids = {i for i, _ in resolve(spec)[1]}
                individuals = db.read_parquet(str(staging / name / 'individual_runs.parquet'))
                actual_ids = {r[0] for r in individuals.project('run_id').fetchall()}
                if actual_ids != expected_ids or result['run_count'] != len(expected_ids):
                    raise ValueError('study run membership mismatch')
                all_ids.update(actual_ids)
            total += result['run_count']
            charts = []
            for metric in metrics:
                points = [r for r in rows if r['metric'] == metric]
                if len(points) != len(spec['vary'][parameter]) or any(r['run_count'] != len(spec['seeds']) or r['seeds'] != spec['seeds'] for r in points):
                    raise ValueError('study conditions / paired seeds do not reconcile')
                charts.append(dict(metric=metric, title=LABELS[metric], unit=points[0]['unit'], definition=points[0]['definition'],
                                   points=[{k: r[k] for k in ('value','run_count','valid_count','null_count','mean','stddev','minimum','maximum')} for r in points],
                                   finding=phrase(points)))
            panels.append(dict(id=name, title=title, parameter=parameter, axis=axis, charts=charts))
        with duckdb.connect() as db:
            db.read_parquet([str(staging / n / 'individual_runs.parquet') for n in DIMENSIONS], hive_partitioning=False).order('experiment_id,run_id').write_parquet(str(staging / 'individual_runs.parquet'), compression='zstd')
            db.read_parquet([str(staging / n / (n + '.parquet')) for n in DIMENSIONS], hive_partitioning=False).order('analysis,condition,metric').write_parquet(str(staging / 'aggregates.parquet'), compression='zstd')
        limitations = [*NOTES,
            'Scenario seeds are paired; the sensor layout seed is fixed. This is not a sample of all possible networks.',
            'The same baseline configuration appears in multiple one-variable sweeps; memberships are not independent additional evidence.',
            'Range-gated matched-track RMSE can improve when hard targets are missed. Read misses and ID switches alongside RMSE.',
            'Changing sensor count also changes network geometry and cadence composition in the existing generator.']
        summary = dict(schema_version=1, study_id=identity(specs), name=definition['name'], question=definition['question'],
                       run_count=total, unique_run_configurations=len(all_ids), seeds_per_condition=len(next(iter(specs.values()))['seeds']),
                       definition=definition, resolved_sweeps=specs, panels=panels, provenance=manifests,
                       duckdb_version=duckdb.__version__, limitations=limitations,
                       implementation_sha256={p: digest(Path(__file__).resolve().parents[1] / p) for p in (
                           'experiments/study.py', 'experiments/sweep.py', 'scripts/procedural.py',
                           'analytics/canonical.py', 'analytics/analysis.py', 'evaluation/metrics.py')})
        (staging / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + '\n')
        lines = ['# ' + summary['name'], '', summary['question'], '',
                 f"{total} run executions; {len(all_ids)} distinct run configurations; {summary['seeds_per_condition']} paired scenario seeds per condition.", '',
                 '## Configuration', '', '```json', json.dumps(definition, indent=2, sort_keys=True), '```', '',
                 'Each sweep changes one variable. Complete resolved defaults and source hashes are in summary.json. Timing is recorded separately in execution.json.', '']
        for p in panels:
            lines += ['## ' + p['title'], '']
            for c in p['charts']:
                lines += [c['finding'] + '.', '', c['definition'], '',
                          '| Condition | Runs / valid | Mean | Sample SD | Min | Max |', '| --- | --- | --- | --- | --- | --- |']
                for point in c['points']:
                    def number(k):
                        return 'null' if point[k] is None else f"{point[k]:.4f}"
                    lines += [f"| {point['value']:g} | {point['run_count']} / {point['valid_count']} | {number('mean')} | {number('stddev')} | {number('minimum')} | {number('maximum')} |"]
                lines += ['']
        lines += ['## Limitations', '', *['- ' + s for s in limitations]]
        (staging / 'report.md').write_text('\n'.join(lines) + '\n')
        write_view(summary, staging / 'results.view')
        (staging / 'manifest.json').write_text(json.dumps(dict(schema_version=1, study_id=summary['study_id'],
            files={p.name: digest(p) for p in sorted(staging.iterdir()) if p.is_file()}), indent=2, sort_keys=True) + '\n')
        staging.rename(output)
    return summary


def write_view(summary, path):
    """Small versioned display export, read directly by C++ without Python/DuckDB."""
    q = lambda value: json.dumps(value, ensure_ascii=True)
    lines = ['SENSOR_STUDY 1', f"STUDY {q(summary['name'])} {q(summary['question'])} {q(summary['study_id'])} {summary['run_count']} {summary['seeds_per_condition']}"]
    for p in summary['panels']:
        lines.append(f"PANEL {q(p['id'])} {q(p['title'])} {q(p['axis'])}")
        for c in p['charts']:
            lines.append(f"CHART {q(p['id'])} {q(c['metric'])} {q(c['title'])} {q(c['unit'])} {q(c['definition'])} {q(c['finding'])}")
            for point in c['points']:
                values = [point[k] if point[k] is not None else 0 for k in ('value','run_count','valid_count','mean','stddev','minimum','maximum')]
                lines.append(f"POINT {q(p['id'])} {q(c['metric'])} " + ' '.join(format(v, '.17g') for v in values))
    lines.append('END')
    path.write_text('\n'.join(lines) + '\n', encoding='ascii')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('generate')
    run.add_argument('--spec', type=Path, default=Path(__file__).parent / 'configs/curated-study.json')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--runtime', type=Path, required=True)
    report = sub.add_parser('analyze')
    report.add_argument('source', type=Path)
    report.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'generate':
            result = generate(json.loads(args.spec.read_text()), args.output, args.runtime)
        else:
            summary = analyze_study(args.source, args.output)
            result = dict(run_count=summary['run_count'], study_id=summary['study_id'])
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(f'study: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
