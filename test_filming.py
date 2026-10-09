"""Local HTTP integration tests; never contacts NH or calls an AI provider."""
import json
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from server import Handler


class FilmingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body=None, origin=None):
        headers = {'Origin': origin or self.base, 'Content-Type': 'application/json'}
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except HTTPError as e:
            return e.code, e.read().decode()

    def payload(self, **updates):
        args = dict(dataset='sample', mode='fixture', start='2026-09-14', end='2026-09-23', initial='1000000', fee='0.001')
        args.update(updates)
        return args

    def test_page_and_filming_preset_assets(self):
        status, body = self.request('/?preset=filming')
        self.assertEqual(status, 200)
        self.assertIn('AI 판단으로 백테스트', body)
        self.assertIn("get('preset')==='filming'", self.request('/app.js')[1])

    def test_sample_explicitly_not_ai(self):
        status, body = self.request('/api/run', self.payload())
        self.assertEqual(status, 200)
        r = json.loads(body)
        self.assertEqual(r['ai_mode'], 'fixture-not-ai')
        self.assertEqual(r['source'], 'synthetic')

    def test_no_private_files(self):
        for path in ['/.env', '/private/token.json', '/cache', '/datasets/nh-005930.json', '/../.env']:
            self.assertEqual(self.request(path)[0], 404)

    def test_no_order_route(self):
        self.assertEqual(self.request('/api/order', {})[0], 404)

    def test_cross_origin_rejected(self):
        self.assertEqual(self.request('/api/run', self.payload(), 'https://example.test')[0], 403)

    def test_live_ai_mode_rejected(self):
        self.assertEqual(self.request('/api/run', self.payload(mode='codex'))[0], 400)

    def test_real_record_replay_when_locally_prepared(self):
        items = json.loads(self.request('/api/datasets')[1])
        if not any(d['id'] == 'nh-005930' for d in items):
            self.skipTest('개인 NH 데이터 없음: 공개 패키지에는 포함하지 않음')
        args = self.payload(dataset='nh-005930', mode='replay')
        status, body = self.request('/api/run', args)
        self.assertEqual(status, 200, body)
        r = json.loads(body)
        self.assertEqual(r['source'], 'nh_period')
        self.assertEqual(r['ai_mode'], 'codex-cli')
        self.assertEqual(len(r['signals']), 8)
        self.assertAlmostEqual(r['final'], r['cash'] + r['shares'] * r['bars'][-1]['close'])
        self.assertEqual(self.request('/api/run', dict(args, mode='fixture'))[0], 400)
        self.assertEqual(self.request('/api/run', dict(args, initial='999999'))[0], 400)


if __name__ == '__main__':
    unittest.main()
