"""Focused study planning, persisted analysis and graphical export tests."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from experiments.study import DIMENSIONS, plan, generate, analyze_study, phrase
from experiments.sweep import resolve
from scripts import dev

ROOT=Path(__file__).resolve().parents[2]
DEFINITION=json.loads((ROOT/'experiments/configs/curated-study.json').read_text())
RUNTIME=Path(os.environ.get('SENSOR_PLATFORM_RUNTIME', ROOT/'build/Debug/sensor_platform.exe'))


class StudyConfigTests(unittest.TestCase):
    def test_curated_design_is_paired_one_variable_and_300_runs(self):
        specs=plan(DEFINITION)
        identifiers=[]
        for name,spec in specs.items():
            parameter=DIMENSIONS[name][0]
            self.assertEqual(spec['seeds'],list(range(2026,2046)))
            runs=resolve(spec)[1]
            self.assertEqual(len(runs),60)
            reference=None
            for run_id,c in runs:
                identifiers.append(run_id)
                controls=asdict(c)
                del controls[parameter]
                del controls['scenario_seed']
                self.assertEqual(c.duration,20)
                if reference is None: reference=controls
                self.assertEqual(controls,reference)
        self.assertEqual(len(identifiers),300)
        self.assertEqual(len(set(identifiers)),240)

    def test_invalid_extra_dimension_or_cartesian_grid_rejected(self):
        for change in ('extra','cartesian','seeds','control'):
            spec=deepcopy(DEFINITION)
            if change=='extra': spec['dimensions']['extra']={'noise':[0,1]}
            if change=='cartesian': spec['dimensions']['noise']['reliability']=[.5,1]
            if change=='seeds': spec['seeds']=[1,1]
            if change=='control': spec['fixed']['noise']=2
            with self.assertRaises(ValueError): plan(spec)

    def test_descriptive_nonmonotonic_and_null_findings(self):
        rows=[dict(metric='position_rmse',mean=v,unit='m') for v in (1,3,2)]
        self.assertIn('non-monotonic',phrase(rows))
        rows[0]['mean']=None
        self.assertIn('no matches',phrase(rows))

    def test_results_route_only_to_existing_viewer(self):
        commands=dev.commands(dev.parser().parse_args(['results','saved/results.view','--page','2']))
        self.assertEqual(len(commands),1)
        self.assertEqual(commands[0][1:],['--results','saved/results.view','--page','2'])
        commands=dev.commands(dev.parser().parse_args(['study','analyze','saved']))
        self.assertNotIn('--runtime',commands[0])


class StudyOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.source=Path(cls.temporary.name)/'study'
        spec=deepcopy(DEFINITION)
        spec['name']='Small study test'
        spec['seeds']=[2026]
        spec['fixed']['duration']=4
        for values in spec['dimensions'].values():
            for p,v in values.items(): values[p]=[v[0],v[-1]]
        cls.result=generate(spec,cls.source,RUNTIME)

    def test_counts_view_contract_and_null_spread(self):
        summary=json.loads((self.source/'analysis/summary.json').read_text())
        self.assertEqual(summary['run_count'],10)
        self.assertEqual(summary['seeds_per_condition'],1)
        self.assertEqual(len(summary['panels']),5)
        with duckdb.connect() as db:
            self.assertEqual(db.read_parquet(str(self.source/'analysis/individual_runs.parquet')).count('*').fetchone()[0],10)
            db.read_parquet(str(self.source/'analysis/aggregates.parquet')).create_view('stats')
            self.assertEqual(db.execute('SELECT DISTINCT n FROM (SELECT sum(run_count) n FROM stats GROUP BY analysis,metric)').fetchall(),[(2,)])
        view=(self.source/'analysis/results.view').read_text()
        self.assertTrue(view.startswith('SENSOR_STUDY 1\n'))
        self.assertTrue(view.endswith('END\n'))
        self.assertEqual(view.count('\nPANEL '),5)
        for panel in summary['panels']:
            for chart in panel['charts']:
                self.assertTrue(all(p['stddev'] is None for p in chart['points']))

    def test_analysis_repeat_is_identical_and_never_executes_simulation(self):
        second=Path(self.temporary.name)/'repeat'
        with patch('subprocess.run',side_effect=AssertionError('persisted analysis must not execute simulation')):
            analyze_study(self.source,second)
        first=self.source/'analysis'
        self.assertEqual({str(p.relative_to(first)):p.read_bytes() for p in first.rglob('*') if p.is_file()},
                         {str(p.relative_to(second)):p.read_bytes() for p in second.rglob('*') if p.is_file()})
        with self.assertRaises(FileExistsError): analyze_study(self.source)


if __name__=='__main__': unittest.main()
