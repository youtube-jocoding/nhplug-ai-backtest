"""Local-only onboarding. Keys never returned by HTTP, printed, or sent to Codex."""
import argparse
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

from server import Handler as DashboardHandler
from ai_provider import CodexProvider
from engine import run
from nh_data import normalize
import nh_client

ROOT = Path(__file__).resolve().parent


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(tmp, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save_keys(values):
    if set(values) != {'key', 'secret'}:
        raise ValueError('앱키와 앱시크릿을 모두 입력하세요.')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 4096 or any(ord(c) < 32 for c in v) for v in values.values()):
        raise ValueError('키가 비어 있거나 형식이 올바르지 않습니다.')
    key, secret = values['key'].strip(), values['secret'].strip()
    query = urlencode(dict(appkey=key, appsecretkey=secret, grant_type='client_credentials', scope='oob'))
    raw, _ = nh_client.request(nh_client.BASE + '/oauth2/token?' + query, '',
                              {'Content-Type': 'application/x-www-form-urlencoded'})
    if not isinstance(raw.get('access_token'), str) or not raw['access_token']:
        raise ValueError('NH 인증 실패. 기존 설정은 유지됩니다.')
    import hashlib
    private_write(ROOT / 'private/keys.json', {'NH_KEY': key, 'NH_SECRET': secret})
    private_write(nh_client.CACHE, dict(access_token=raw['access_token'],
        key_hash=hashlib.sha256((key + '\0' + secret).encode()).hexdigest(),
        expires_at=time.time() + int(raw.get('expires_in', 86400))))


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.stage = 'ready'
        self.message = 'NH 키를 연결하고 시작하세요.'
        self.busy = False
        self.token = secrets.token_urlsafe(32)
        self.expires = time.monotonic() + 600
        self.cookie = secrets.token_urlsafe(32)

    def job(self):
        try:
            self.stage, self.message = 'prices', 'NH 과거 시세를 읽고 있습니다. 실제 주문은 하지 않습니다.'
            raw = nh_client.fetch('005930', '2026-09-23', 400)
            data = normalize(raw, '005930', datetime.now(timezone.utc).isoformat(), '2026-09-23', reviewed=True)
            self.stage, self.message = 'ai', '8거래일의 AI 판단을 생성합니다. 수 분 걸릴 수 있습니다.'
            provider = CodexProvider(ROOT / 'cache')
            result = run(data, '2026-09-14', '2026-09-23', '1000000', '0.001', provider)
            result['ai_mode'] = 'codex-cli'
            result['generated_at'] = datetime.now(timezone.utc).isoformat()
            # Publish inputs/result only after the whole run succeeds.
            private_write(ROOT / 'datasets/nh-005930.json', data)
            private_write(ROOT / 'runs/nh-codex.json', result)
            self.stage, self.message = 'done', '완료! 결과 화면에서 판단 이유와 가상 거래를 확인하세요.'
        except Exception:
            # Do not return raw vendor errors, credential-bearing URLs or traces.
            self.stage, self.message = 'error', '실행을 완료하지 못했습니다. NH 이용 권한·네트워크·Codex 로그인/이용량을 확인한 뒤 다시 시도하세요. 가짜 결과로 대체하지 않았습니다.'
        finally:
            with self.lock:
                self.busy = False


class Handler(DashboardHandler):
    def log_message(self, *_):
        pass  # Access logs must never include one-use login tokens.

    def authenticated(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get('Cookie', ''))
            return 'nh_backtest' in c and secrets.compare_digest(c['nh_backtest'].value, self.server.state.cookie)
        except Exception:
            return False

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': '로컬 접속만 허용합니다.'})
        parsed = urlsplit(self.path)
        state = self.server.state
        if parsed.path == '/start':
            token = parse_qs(parsed.query).get('token', [''])[0]
            with state.lock:
                valid = bool(state.token) and time.monotonic() < state.expires and secrets.compare_digest(token, state.token)
                if valid:
                    state.token = ''
            if not valid:
                return self.reply(403, {'error': '접속 링크가 만료되었거나 사용됐습니다. Codex에 설정 화면을 다시 열어 달라고 요청하세요.'})
            self.send_response(303)
            self.send_header('Location', '/setup')
            self.send_header('Set-Cookie', 'nh_backtest=' + state.cookie + '; HttpOnly; SameSite=Strict; Path=/')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if not self.authenticated():
            return self.reply(401, {'error': 'Codex가 제공한 설정 링크로 접속하세요.'})
        if parsed.path in ('/setup', '/setup.js', '/setup.css'):
            file, kind = {'/setup': ('setup.html', 'text/html'), '/setup.js': ('setup.js', 'text/javascript'),
                          '/setup.css': ('setup.css', 'text/css')}[parsed.path]
            return self.reply(200, (ROOT / 'web' / file).read_bytes(), kind)
        if parsed.path == '/api/status':
            try:
                nh_client.credentials()
                connected = True
            except (OSError, ValueError):
                connected = False
            return self.reply(200, dict(stage=state.stage, message=state.message, busy=state.busy, keys_saved=connected))
        return super().do_GET()

    def do_POST(self):
        origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if not self.valid_host() or not self.authenticated() or self.headers.get('Origin') not in origins:
            return self.reply(403, {'error': '인증된 로컬 화면에서만 가능합니다.'})
        if self.path not in ('/api/keys', '/api/start'):
            return super().do_POST()
        state = self.server.state
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size < 12000:
                raise ValueError('입력 크기 오류')
            data = json.loads(self.rfile.read(size))
            with state.lock:
                if state.busy:
                    return self.reply(409, {'error': '진행 중입니다. 완료될 때까지 기다려 주세요.'})
                if self.path == '/api/keys':
                    save_keys(data)
                    return self.reply(200, {'message': 'NH 연결 완료. 이제 백테스트를 시작하세요.'})
                if data != {'consent': True}:
                    raise ValueError('시세 조회와 AI 사용량 발생에 동의해 주세요.')
                nh_client.credentials()
                provider = CodexProvider(ROOT / 'cache')
                if not provider.binary or not shutil.which('curl'):
                    raise ValueError('Codex CLI 또는 curl이 없습니다. Codex에 설치를 요청하세요.')
                state.busy = True
                state.stage, state.message = 'starting', '시작 준비 중…'
                threading.Thread(target=state.job, daemon=True).start()
            return self.reply(202, {'message': '시작했습니다.'})
        except Exception:
            return self.reply(400, {'error': '연결 또는 입력 확인이 필요합니다. 키 발급·NH 권한·Codex 설치를 확인하세요. 키나 오류 원문은 표시하지 않습니다.'})


def make_server(port=8771):
    try:
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    except OSError:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.state = State()
    return server


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--open', action='store_true')
    p.add_argument('--port', type=int, default=8771)
    a = p.parse_args()
    server = make_server(a.port)
    url = f'http://127.0.0.1:{server.server_port}/start?token={server.state.token}'
    print('설정 화면 (10분 동안 한 번 사용 가능): ' + url, flush=True)
    if a.open:
        webbrowser.open(url)
    server.serve_forever()
