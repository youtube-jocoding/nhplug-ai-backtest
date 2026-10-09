import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from engine import run
from run import synthetic
from scenarios import DEFAULTS, parse, validate_experiment
import setup


class ScenarioTests(unittest.TestCase):
    def prices(self):
        data = synthetic()
        data.update(symbol='005930', source='nh_period')
        for b in data['bars']:
            p = 98000 if b['date'] >= '2026-09-16' else 100000
            b.update(open=p, close=p, high=p+1, low=p-1)
        return data

    def config(self, **updates):
        return parse(dict(DEFAULTS, end='2026-09-18', use_high=False, **updates))

    def test_prompt_is_part_of_actual_ai_input_and_fingerprint(self):
        inputs = []
        def judge(s):
            inputs.append(copy.deepcopy(s))
            return dict(decision='buy', reason='test only', provider='codex-cli')
        c = self.config(prompt='신중한 판단 테스트')
        a = run(self.prices(), c['start'], c['end'], c['initial'], '.0001', judge,
                official_costs=True, strategy_config=c)
        c2 = dict(c, prompt='흐름 중심 판단 테스트')
        b = run(self.prices(), c2['start'], c2['end'], c2['initial'], '.0001', judge,
                official_costs=True, strategy_config=c2)
        self.assertIn(c['prompt'], inputs[0]['instructions'])
        self.assertEqual(inputs[0]['strategy_config'], c)
        self.assertNotEqual(a['signals'][0]['input_hash'], b['signals'][0]['input_hash'])
        self.assertEqual(len(inputs), 10)

    def test_amount_and_stop_loss_change_actual_executions(self):
        judge = lambda s: dict(decision='buy', reason='test only', provider='codex-cli')
        c = self.config(buy_amount=200000, stop_loss=1)
        result = run(self.prices(), c['start'], c['end'], c['initial'], '.0001', judge,
                     official_costs=True, strategy_config=c)
        self.assertEqual(result['trades'][0]['quantity'], 2)
        self.assertEqual(result['signals'][2]['action'], 'SELL')
        self.assertEqual(result['trades'][1]['date'], '2026-09-17')
        self.assertEqual(result['trades'][1]['side'], 'SELL')
        self.assertEqual(DEFAULTS['buy_amount'], 300000)

    def test_invalid_configuration_rejected(self):
        for values in [dict(initial=float('nan')), dict(short_days=30, long_days=20),
                       dict(prompt=''), dict(use_macd='false'), dict(stop_loss=-5),
                       dict(start='2025-01-01'), dict(unknown=1)]:
            with self.assertRaises(ValueError):
                parse(values)

    def test_missing_or_synthetic_prices_rejected_before_ai(self):
        c = self.config()
        with self.assertRaises(ValueError):
            validate_experiment(synthetic(), c)
        with self.assertRaises(ValueError):
            validate_experiment(self.prices(), dict(c, end='2026-12-31'))

    def test_repeated_jobs_get_independent_ai_caches_and_saved_records(self):
        caches = []
        class FakeCodex:
            def __init__(self, cache):
                caches.append(str(cache))
                self.calls = 0
            def __call__(self, snap):
                self.calls += 1
                return dict(decision='hold', reason='test fixture only', provider='codex-cli')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'datasets').mkdir()
            (root / 'datasets/nh-005930.json').write_text(json.dumps(self.prices()), encoding='utf-8')
            with patch.object(setup, 'ROOT', root), patch.object(setup, 'CodexProvider', FakeCodex):
                state = setup.State()
                state.scenario_job(self.config())
                self.assertEqual(state.stage, 'done')
                self.assertEqual(state.scenario_result['result']['ai_calls'], 5)
                state.scenario_job(self.config())
                self.assertEqual(state.stage, 'done')
                self.assertEqual(len(list((root / 'runs/experiments').glob('*.json'))), 2)
                self.assertNotEqual(caches[0], caches[1])

    def test_failed_ai_job_does_not_publish_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'datasets').mkdir()
            (root / 'datasets/nh-005930.json').write_text(json.dumps(self.prices()), encoding='utf-8')
            with patch.object(setup, 'ROOT', root), patch.object(setup, 'CodexProvider', side_effect=RuntimeError('test failure')):
                state = setup.State()
                state.scenario_job(self.config())
                self.assertEqual(state.stage, 'error')
                self.assertIsNone(state.scenario_result)
                self.assertFalse((root / 'runs/experiments').exists())
