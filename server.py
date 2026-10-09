"""Loopback-only filming UI. No live AI calls, credentials, orders or file upload routes."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit
from engine import run, validate_dataset
from run import synthetic
from ai_provider import fixture_provider, CodexProvider

HERE = Path(__file__).parent


def datasets():
    items = {'sample': synthetic()}
    for f in (HERE / 'datasets').glob('*.json'):
        item = json.loads(f.read_text())
        validate_dataset(item)
        items[f.stem] = item
    return items


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, kind='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': '로컬 호스트만 허용'})
        path = urlsplit(self.path).path
        if path == '/api/datasets':
            return self.reply(200, [{'id': k, 'name': v.get('name', k), 'source': v['source'],
                                     'first': v['bars'][0]['date'], 'last': v['bars'][-1]['date']}
                                    for k, v in datasets().items()])
        paths = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
        if path not in paths:
            return self.reply(404, {'error': '없는 경로'})
        kind = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[path]
        return self.reply(200, (HERE / 'web' / paths[path]).read_bytes(), kind)

    def do_POST(self):
        expected = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if not self.valid_host() or self.headers.get('Origin') not in expected:
            return self.reply(403, {'error': '동일 출처의 로컬 화면에서만 실행 가능'})
        if self.path != '/api/run':
            return self.reply(404, {'error': '없는 경로'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size < 4096:
                raise ValueError('요청 크기 오류')
            args = json.loads(self.rfile.read(size))
            data = datasets()[args['dataset']]
            if args['mode'] not in ('fixture', 'replay'):
                raise ValueError('지원하지 않는 실행 모드')
            if data['source'] != 'synthetic' and args['mode'] == 'fixture':
                raise ValueError('실제 NH 데이터에 가상 판단을 섞지 않습니다. 실제 Codex 기록을 먼저 생성하세요')
            provider = fixture_provider if args['mode'] == 'fixture' else CodexProvider(HERE / 'cache', replay_only=True)
            result = run(data, args['start'], args['end'], args['initial'], args['fee'], provider)
            result['ai_mode'] = 'fixture-not-ai' if args['mode'] == 'fixture' else 'codex-cli'
            self.reply(200, result)
        except (ValueError, KeyError, TypeError, ArithmeticError) as e:
            self.reply(400, {'error': str(e)})


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=8769)
    a = p.parse_args()
    print(f'http://127.0.0.1:{a.port} · 실제 주문 기능 없음', flush=True)
    ThreadingHTTPServer(('127.0.0.1', a.port), Handler).serve_forever()
