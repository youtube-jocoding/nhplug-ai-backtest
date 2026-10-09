import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(setup, 'ROOT', self.root),
                        patch.object(setup.nh_client, 'ROOT', self.root),
                        patch.object(setup.nh_client, 'CACHE', self.root / 'private/token.json')]
        for p in self.patches:
            p.start()
        self.server = setup.make_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ''

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def request(self, path, body=None, origin=True, host=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Cookie': self.cookie}
        if origin:
            headers['Origin'] = f'http://127.0.0.1:{self.server.server_port}'
        if host:
            headers['Host'] = host
        c.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        result = r.status, dict(r.getheaders()), r.read().decode()
        c.close()
        return result

    def login(self):
        status, headers, _ = self.request('/start?token=' + self.server.state.token)
        self.assertEqual(status, 303)
        self.cookie = headers['Set-Cookie'].split(';')[0]

    def test_unauthenticated_read_and_write_blocked(self):
        self.assertEqual(self.request('/api/status')[0], 401)
        self.assertEqual(self.request('/api/keys', {})[0], 403)

    def test_bootstrap_token_one_use(self):
        token = self.server.state.token
        self.login()
        self.assertEqual(self.request('/start?token=' + token)[0], 403)
        self.assertEqual(self.request('/api/status')[0], 200)

    def test_expired_token(self):
        self.server.state.expires = 0
        self.assertEqual(self.request('/start?token=' + self.server.state.token)[0], 403)

    def test_host_and_origin_block(self):
        self.login()
        self.assertEqual(self.request('/api/keys', {}, origin=False)[0], 403)
        self.assertEqual(self.request('/api/status', host='attacker.test')[0], 403)

    def test_valid_keys_saved_not_returned(self):
        self.login()
        with patch.object(setup.nh_client, 'request', return_value=({'access_token': 'fake-token', 'expires_in': 1000}, {})):
            status, _, body = self.request('/api/keys', {'key': 'dummy-key', 'secret': 'dummy-secret'})
        self.assertEqual(status, 200)
        self.assertNotIn('dummy-secret', body)
        self.assertNotIn('fake-token', self.request('/api/status')[2])
        self.assertEqual(json.loads((self.root / 'private/keys.json').read_text())['NH_KEY'], 'dummy-key')
        import os
        if os.name != 'nt':
            self.assertEqual((self.root / 'private/keys.json').stat().st_mode & 0o777, 0o600)

    def test_invalid_keys_preserve_previous(self):
        setup.private_write(self.root / 'private/keys.json', {'NH_KEY': 'old', 'NH_SECRET': 'old'})
        self.login()
        with patch.object(setup.nh_client, 'request', return_value=({}, {})):
            self.assertEqual(self.request('/api/keys', {'key': 'new', 'secret': 'invalid'})[0], 400)
        self.assertEqual(json.loads((self.root / 'private/keys.json').read_text())['NH_KEY'], 'old')

    def test_no_consent_no_run(self):
        self.login()
        self.assertEqual(self.request('/api/start', {'consent': False})[0], 400)
        self.assertFalse(self.server.state.busy)

    def test_inflight_run_cannot_repeat_or_change_keys(self):
        self.login()
        self.server.state.busy = True
        self.assertEqual(self.request('/api/start', {'consent': True})[0], 409)
        self.assertEqual(self.request('/api/keys', {})[0], 409)

    def test_job_failure_does_not_publish_fake_result(self):
        state = setup.State()
        state.busy = True
        with patch.object(setup.nh_client, 'fetch', side_effect=RuntimeError('SECRET MUST NOT LEAK')):
            state.job()
        self.assertEqual(state.stage, 'error')
        self.assertNotIn('SECRET', state.message)
        self.assertFalse((self.root / 'runs/nh-codex.json').exists())
        self.assertFalse(state.busy)

    def test_keys_format_rejected_before_network(self):
        with patch.object(setup.nh_client, 'request') as network:
            for keys in [{}, {'key': '', 'secret': 'x'}, {'key': 'a\nb', 'secret': 'x'}]:
                with self.assertRaises(ValueError):
                    setup.save_keys(keys)
            network.assert_not_called()

    def test_occupied_port_fallback(self):
        other = setup.make_server(self.server.server_port)
        try:
            self.assertNotEqual(other.server_port, self.server.server_port)
        finally:
            other.server_close()


if __name__ == '__main__':
    unittest.main()
