import copy
from decimal import Decimal
import unittest
from costs import charges, reprice_saved, validate_scope
from engine import run
from run import synthetic


class OfficialCostsTests(unittest.TestCase):
    def test_buy_and_sell_300000(self):
        buy, sell = charges(300000, 'BUY'), charges(300000, 'SELL')
        self.assertEqual(buy['cost'], Decimal('30'))
        self.assertEqual(sell['commission'], Decimal('30'))
        self.assertEqual(sell['transaction_tax'], Decimal('150'))
        self.assertEqual(sell['rural_tax'], Decimal('450'))
        self.assertEqual(buy['cost'] + sell['cost'], Decimal('660'))

    def test_scope_does_not_apply_kospi_tax_to_other_markets_or_years(self):
        for args in [('AAPL', '2026-09-14', '2026-09-23'),
                     ('005930', '2025-09-14', '2025-09-23')]:
            with self.assertRaises(ValueError):
                validate_scope(*args)

    def ledger(self, sell=True, official=False):
        data = synthetic()
        data['symbol'] = '005930'
        for b in data['bars']:
            if b['date'] >= '2026-09-14':
                b.update(open=100000, close=100000, high=100001, low=99999)
            else:
                b.update(open=150000, close=150000, high=150001, low=149999)
        def provider(s):
            action = 'buy' if s['date'] == '2026-09-14' else ('sell' if sell else 'hold')
            return dict(decision=action, reason='test only', provider='test')
        return run(data, '2026-09-14', '2026-09-18', 1000000, '.001', provider, official_costs=official)

    def test_official_engine_hand_ledger(self):
        r = self.ledger(official=True)
        self.assertEqual(len(r['trades']), 2)
        self.assertEqual(r['trades'][0]['quantity'], 3)
        self.assertEqual(r['trades'][0]['cash_after'], 699970)
        self.assertEqual(r['final'], 999340)
        self.assertEqual(r['profit'], -660)

    def test_unrealized_holding_does_not_pay_sell_tax(self):
        r = self.ledger(sell=False, official=True)
        self.assertEqual(r['shares'], 3)
        self.assertEqual(r['final'], 999970)
        self.assertEqual(r['trades'][0]['transaction_tax'], 0)

    def test_repricing_preserves_original_ai_and_does_not_mutate_source(self):
        old = self.ledger()
        # Explicit synthetic test envelope; never published or used by the UI.
        old.update(source='nh_period', ai_mode='codex-cli')
        original = copy.deepcopy(old)
        new = reprice_saved(old)
        self.assertEqual(new['final'], 999340)
        self.assertEqual(new['signals'], old['signals'])
        self.assertEqual(old, original)
        self.assertEqual(new['original_run_hash'], old['run_hash'])
        self.assertEqual(new['calculation_mode'], 'fixed_trades_repriced')

    def test_synthetic_cannot_be_relabelled_as_real(self):
        with self.assertRaises(ValueError):
            reprice_saved(self.ledger())
