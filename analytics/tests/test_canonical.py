"""Canonical SQL tests use tiny stored tables, never a simulation subprocess."""
import csv
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from analytics.analysis import SCHEMAS
from analytics.canonical import ANALYSES, analyze
from analytics.dataset import digest
from scripts import dev


class CanonicalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'sweep'
        self.source.mkdir()
        with duckdb.connect() as db:
            db.execute('CREATE TABLE runs (' + SCHEMAS['runs'] + ')')
            for run, seed, noise, layout in [(1, 1, 0, 73), (2, 2, 0, 73), (3, 1, 2, 73), (4, 2, 2, 73)]:
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           [run, 'procedural-v1', seed, layout, 4, 4, 3, 8, 14, 16, 1, 1, 1, 1, 1, noise, 1, 1])
            db.execute("CREATE TABLE experiments AS SELECT 'example' experiment_id, 'test' experiment_name, scenario_seed seed, r.* FROM runs r")
            db.execute('''CREATE TABLE experiment_metrics (
                experiment_id VARCHAR,experiment_name VARCHAR,run_id UBIGINT,seed UINTEGER,
                evaluator_version VARCHAR,fusion_config VARCHAR,evaluation_gate DOUBLE,
                position_rmse DOUBLE,missed_target_samples UBIGINT,target_samples UBIGINT,
                id_switches UBIGINT,measurement_count UBIGINT,measurements_per_second DOUBLE,
                measurements_per_scan DOUBLE,false_track_samples UBIGINT,unique_false_tracks UBIGINT)''')
            for run, seed, rmse, misses in [(1, 1, 1, 2), (2, 2, 3, 6), (3, 1, None, 8), (4, 2, 5, 4)]:
                db.execute('INSERT INTO experiment_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           ['example', 'test', run, seed, 'v1', '{}', 5, rmse, misses, 8, run, 20, 5, 2, run*2, 1])
            for table in ('experiments', 'experiment_metrics'):
                db.table(table).order('run_id').write_parquet(str(self.source / (table + '.parquet')))
        self.refresh_manifest()

    def refresh_manifest(self):
        (self.source / 'manifest.json').write_text(json.dumps(dict(schema_version=1, experiment_id='example', name='test', run_count=4,
            files={t: digest(self.source / (t + '.parquet')) for t in ('experiments', 'experiment_metrics')})))

    def rewrite(self, table, expression):
        with duckdb.connect() as db:
            db.read_parquet(str(self.source / (table + '.parquet'))).create_view('original')
            db.sql(expression).write_parquet(str(self.source / 'replacement.parquet'))
        (self.source / 'replacement.parquet').replace(self.source / (table + '.parquet'))
        self.refresh_manifest()

    def test_known_means_spread_nulls_schema_and_counts(self):
        output = self.root / 'analysis'
        with patch('subprocess.run', side_effect=AssertionError('analysis must never execute a runtime')):
            summary = analyze(self.source, output)
        self.assertEqual((summary['run_count'], summary['condition_count']), (4, 2))
        with duckdb.connect() as db:
            for name in ANALYSES:
                db.read_parquet(str(output / (name + '.parquet'))).create_view(name)
                self.assertEqual(db.execute(f'SELECT DISTINCT run_count,seed_count FROM {name}').fetchall(), [(2, 2)])
                self.assertTrue(all(r[0] == 4 for r in db.execute(f'SELECT sum(run_count) FROM {name} GROUP BY metric').fetchall()))
                self.assertEqual(db.execute(f'SELECT count(*) FROM {name} WHERE valid_count+null_count != run_count').fetchone()[0], 0)
                with (output / (name + '.csv')).open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), db.table(name).count('*').fetchone()[0])
                self.assertTrue({'mean', 'stddev', 'minimum', 'maximum', 'unit', 'definition', 'condition', 'seeds'} <= rows[0].keys())
            rmse = db.execute("SELECT noise,mean,stddev,minimum,maximum,valid_count,null_count,unit FROM noise WHERE metric='position_rmse' ORDER BY noise").fetchall()
            self.assertEqual(rmse[0][0:2], (0, 2))
            self.assertAlmostEqual(rmse[0][2], math.sqrt(2))
            self.assertEqual(rmse[0][3:], (1, 3, 2, 0, 'm'))
            self.assertEqual(rmse[1], (2, 5, None, 5, 5, 1, 1, 'm'))
            self.assertEqual(db.execute("SELECT mean FROM reliability WHERE noise=0 AND metric='missed_target_fraction'").fetchone()[0], .5)
            self.assertEqual(db.read_parquet(str(output / 'individual_runs.parquet')).count('*').fetchone()[0], 4)

    def test_reproducible_outputs_and_source_preserved(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        first, second = self.root / 'a', self.root / 'b'
        analyze(self.source, first)
        analyze(self.source, second)
        self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()}, {p.name: p.read_bytes() for p in second.iterdir()})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        with self.assertRaises(FileExistsError):
            analyze(self.source, first)

    def test_other_controls_are_not_pooled_and_all_null_rmse_remains_null(self):
        self.rewrite('experiments', 'SELECT * REPLACE (CASE WHEN run_id=2 THEN 74 ELSE layout_seed END AS layout_seed) FROM original')
        self.rewrite('experiment_metrics', 'SELECT * REPLACE (NULL::DOUBLE AS position_rmse) FROM original')
        output = self.root / 'analysis'
        self.assertEqual(analyze(self.source, output)['condition_count'], 3)
        with duckdb.connect() as db:
            db.read_parquet(str(output / 'noise.parquet')).create_view('noise')
            self.assertEqual(db.execute("SELECT sum(run_count),sum(valid_count),sum(null_count),count(mean),count(stddev) FROM noise WHERE metric='position_rmse'").fetchone(), (4, 0, 4, 0, 0))

    def test_corruption_and_mismatched_membership_rejected(self):
        path = self.source / 'experiments.parquet'
        with path.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            analyze(self.source)
        self.assertFalse((self.source / 'canonical_analysis').exists())

    def test_duplicate_and_unmatched_run_rejected(self):
        self.rewrite('experiment_metrics', 'SELECT * REPLACE (99::UBIGINT AS run_id) FROM original')
        with self.assertRaisesRegex(ValueError, 'identities'):
            analyze(self.source)
        self.rewrite('experiment_metrics', 'SELECT * REPLACE ((seed + row_number() OVER () * 100)::UBIGINT AS run_id) FROM original')
        with self.assertRaisesRegex(ValueError, 'membership'):
            analyze(self.source)

    def test_developer_command_is_analysis_only(self):
        args = dev.parser().parse_args(['analysis', 'data/sweep', '--output', 'data/report'])
        command = dev.commands(args)
        self.assertEqual(len(command), 1)
        self.assertEqual(command[0][1:], ['-m', 'analytics.canonical', 'data/sweep', '--output', 'data/report'])


if __name__ == '__main__':
    unittest.main()
