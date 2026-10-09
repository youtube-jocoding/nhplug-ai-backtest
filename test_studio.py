import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from engine import run, snapshot, fingerprint, validate_dataset, D
from run import synthetic
from ai_provider import CodexProvider
from nh_data import normalize, URL


def response(action):
    return dict(decision=action, reason='테스트 대역', provider='fixture-not-ai')


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.data = synthetic()
        self.start, self.end = '2026-09-14', '2026-09-18'

    def run_it(self, provider=lambda s: response('hold'), **kwargs):
        return run(self.data, self.start, self.end, kwargs.get('initial', 1000000), kwargs.get('fee', .001), provider)

    def test_hand_ledger_and_delayed_fill(self):
        # Modify only a local fixture; prices intentionally simple for hand arithmetic.
        for b in self.data['bars']:
            if b['date'] >= self.start:
                p = {'2026-09-14':100,'2026-09-15':110,'2026-09-16':112,'2026-09-17':115,'2026-09-18':111}.get(b['date'],111)
                b.update(open=p,close=p,high=p+1,low=p-1)
        r=self.run_it(lambda s: response({'2026-09-14':'buy','2026-09-16':'sell'}.get(s['date'],'hold')))
        qty=2727
        self.assertEqual([t['date'] for t in r['trades']],['2026-09-15','2026-09-17'])
        self.assertEqual([t['quantity'] for t in r['trades']],[qty,qty])
        self.assertAlmostEqual(r['profit'],qty*5-qty*110*.001-qty*115*.001)
        self.assertEqual(r['trades'][0]['signal_date'],'2026-09-14')

    def test_buy_budget_and_cash_nonnegative(self):
        r=self.run_it(lambda s:response('buy'), initial=60000)
        self.assertTrue(all(e['cash']>=0 for e in r['equity']))
        self.assertTrue(all(t['quantity']*t['price']<=300000 for t in r['trades'] if t['side']=='BUY'))

    def test_repeat_buy_not_accumulated(self):
        r=self.run_it(lambda s:response('buy'))
        self.assertEqual(sum(t['side']=='BUY' for t in r['trades']),1)
        self.assertIn('이미 보유', r['signals'][1]['reason'])

    def test_final_signal_unfilled(self):
        r=self.run_it(lambda s:response('buy' if s['date']==self.end else 'hold'))
        self.assertEqual(r['trades'],[])
        self.assertFalse(r['signals'][-1]['executable_next_day'])

    def test_unliquidated_position_marked(self):
        r=self.run_it(lambda s:response('buy'))
        self.assertAlmostEqual(r['final'],r['cash']+r['shares']*r['bars'][-1]['close'])

    def test_no_future_prices_in_snapshot(self):
        original=self.run_it()
        for b in self.data['bars']:
            if b['date']>self.start:
                b.update(open=b['open']*2,high=b['high']*2,low=b['low']*2,close=b['close']*2)
        changed=self.run_it()
        self.assertEqual(original['signals'][0]['input'],changed['signals'][0]['input'])

    def test_snapshot_cutoff_and_original_facts(self):
        r=self.run_it()
        for s in r['signals']:
            self.assertEqual(s['date'],s['input']['information_through'])
            self.assertEqual(s['input_hash'],fingerprint(s['input']))
            self.assertTrue(any('MACD' in f for f in s['indicators']))

    def test_missing_ai_fail_closed(self):
        for ai in [{},response('maybe'),dict(decision='buy',reason='')]:
            with self.assertRaises(ValueError):self.run_it(lambda s:ai)

    def test_provider_failure_not_substituted(self):
        def broken(s):raise RuntimeError('offline')
        with self.assertRaises(RuntimeError):self.run_it(broken)

    def test_warmup_required(self):
        self.data['bars']=self.data['bars'][-40:]
        with self.assertRaises(ValueError):self.run_it()

    def test_missing_turnover(self):
        del self.data['bars'][0]['turnover']
        with self.assertRaises(KeyError):self.run_it()

    def test_nan_duplicate_bad_ohlc_rejected(self):
        for field,value in [('close',float('nan')),('volume',0),('low',999999)]:
            d=copy.deepcopy(self.data);d['bars'][0][field]=value
            with self.assertRaises(ValueError):validate_dataset(d)
        self.data['bars'].append(self.data['bars'][-1])
        with self.assertRaises(ValueError):self.run_it()

    def test_corporate_action_rejected(self):
        self.data['bars'][0]['corporate_action']=True
        with self.assertRaises(ValueError):self.run_it()

    def test_empty_range_out_of_range_bad_fee(self):
        for start,end in [('2026-09-19','2026-09-20'),('2026-09-18','2026-09-14'),('2026-09-14','2030-01-01')]:
            with self.assertRaises(ValueError):run(self.data,start,end,1000000,.001,lambda s:response('hold'))
        for f in [-1,1,float('nan')]:
            with self.assertRaises(ValueError):self.run_it(fee=f)

    def test_input_cache_hash_tracks_state_and_data(self):
        i=next(i for i,b in enumerate(self.data['bars']) if b['date']==self.start)
        a=snapshot(self.data,i,D(1000000),0,D(0))
        b=snapshot(self.data,i,D(500000),0,D(0))
        self.assertNotEqual(fingerprint(a),fingerprint(b))

    def test_replay_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=CodexProvider(tmp,replay_only=True)
            with patch('subprocess.run') as proc:
                with self.assertRaises(ValueError):p({'date':'2026-01-01'})
                proc.assert_not_called()

    def test_replay_cache_verifies_provenance(self):
        snap={'date':'2026-01-01'};key=fingerprint(snap)
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/(key+'.json')
            file.write_text(json.dumps(dict(input=snap,input_hash=key,output=response('hold'),provider='fixture')))
            with self.assertRaises(ValueError):CodexProvider(tmp,True)(snap)

    def test_nh_parser_rejects_error_missing_and_unreviewed(self):
        raw={'message':{'msg_code':'TEST_OK'},'Output_0':{'iem_cd':'005930'},'Output_1':[
            {'bsop_date':'20260914','stck_oprc':'100','stck_hgpr':'120','stck_lwpr':'90',
             'stck_prpr':'110','vol':'1000','tr_pbmn':'110000','fcam_mod_cls_code':'00','flng_cls_code':'00'}]}
        d=normalize(raw,'005930','test','2026-09-14','TEST_OK',True)
        self.assertEqual(d['bars'][0]['close'],110)
        with self.assertRaises(ValueError):normalize(raw,'005930','test','2026-09-14','WRONG',True)
        with self.assertRaises(ValueError):normalize(raw,'005930','test','2026-09-14','TEST_OK',False)
        with self.assertRaises(ValueError):normalize(raw,'000660','test','2026-09-14','TEST_OK',True)
        raw['Output_1'][0]['fcam_mod_cls_code']='01'
        with self.assertRaises(ValueError):normalize(raw,'005930','test','2026-09-14','TEST_OK',True)

    def test_nh_only_readonly_endpoint(self):
        self.assertEqual(URL,'https://api.nhplug.com:8443/krstock/quote/v1/period')

    def test_nh_cached_token_no_network(self):
        import nh_client, time, hashlib
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'token.json'
            p.write_text(json.dumps({'access_token':'TEST_TOKEN','expires_at':time.time()+5000,'key_hash':hashlib.sha256(b'test\0secret').hexdigest()}))
            with patch.object(nh_client,'credentials',return_value={'NH_KEY':'test','NH_SECRET':'secret'}),patch.object(nh_client,'CACHE',p),patch.object(nh_client,'request') as network:
                self.assertEqual(nh_client.token(),'TEST_TOKEN')
                network.assert_not_called()

    def test_nh_order_endpoint_rejected(self):
        import nh_client
        with patch('subprocess.run') as proc:
            with self.assertRaises(ValueError):nh_client.request(nh_client.BASE+'/krstock/order/v1/buy','',{})
            proc.assert_not_called()

    def test_nh_pagination_repeated_key_rejected(self):
        import nh_client
        def page(*a):return {'Output_0':{'iem_cd':'005930'},'rsp_msg':'조회가 완료되었습니다.','Output_1':[{'bsop_date':'20260914'}]}, {'cts_flag':'Y','cts':'same'}
        with patch.object(nh_client,'token',return_value='TEST_TOKEN'),patch.object(nh_client,'request',side_effect=page),patch('time.sleep'):
            with self.assertRaises(RuntimeError):nh_client.fetch('005930','2026-09-25',500)

    def test_nh_errors_fail_without_reissue(self):
        import nh_client
        with patch.object(nh_client,'token',return_value='TEST_TOKEN') as auth,patch.object(nh_client,'request',side_effect=RuntimeError('HTTP 429')):
            with self.assertRaises(RuntimeError):nh_client.fetch('005930','2026-09-25',500)
            self.assertEqual(auth.call_count,1)

    def test_nh_stops_when_requested_count_received(self):
        import nh_client
        raw={'Output_0':{'iem_cd':'005930'},'rsp_msg':'조회가 완료되었습니다.',
             'Output_1':[{'bsop_date':'20260914'},{'bsop_date':'20260915'}]}
        with patch.object(nh_client,'token',return_value='TEST_TOKEN'),patch.object(nh_client,'request',return_value=(raw,{'cts_flag':'Y','cts':'more'})) as network:
            self.assertEqual(len(nh_client.fetch('005930','2026-09-25',2)['Output_1']),2)
            self.assertEqual(network.call_count,1)

    def test_dividend_in_evaluation_rejected(self):
        next(b for b in self.data['bars'] if b['date']==self.start)['dividend_event']=True
        with self.assertRaises(ValueError):self.run_it()

    def test_dividend_in_warmup_not_credited(self):
        self.data['bars'][0]['dividend_event']=True
        self.assertEqual(self.run_it()['final'],1000000)

    def test_nh_rejects_intraday_request_before_auth(self):
        import nh_client
        with patch.object(nh_client,'token') as auth:
            with self.assertRaises(ValueError):nh_client.fetch('005930','2099-01-01',400)
            auth.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
