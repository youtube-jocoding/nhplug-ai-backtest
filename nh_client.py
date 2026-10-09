"""Strictly read-only quote client; credentials never enter CLI arguments or UI."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import hashlib
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'private/token.json'
BASE = 'https://api.nhplug.com:8443'
QUOTE = '/krstock/quote/v1/period'


def credentials():
    key_file = ROOT / 'private/keys.json'
    if key_file.exists() and not os.environ.get('NH_ENV_FILE'):
        values = json.loads(key_file.read_text(encoding='utf-8'))
        if not all(isinstance(values.get(k), str) and values[k] for k in ('NH_KEY', 'NH_SECRET')):
            raise ValueError('로컬 키 설정을 다시 확인하세요')
        return {k: values[k] for k in ('NH_KEY', 'NH_SECRET')}
    values = {}
    env_file = Path(os.environ.get('NH_ENV_FILE', ROOT / '.env'))
    for line in env_file.read_text(encoding='utf-8').splitlines():
        key, sep, value = line.strip().removeprefix('export ').partition('=')
        if sep and key.strip() in ('NH_KEY', 'NH_SECRET'):
            value = value.strip()
            if value[:1] in ('"', "'"):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 0 or (value[end+1:].strip() and not value[end+1:].strip().startswith('#')):
                    raise ValueError('NH 환경변수 따옴표 형식 오류')
                value = value[1:end]
            else:
                value = value.split('#', 1)[0].strip()
            if key.strip() in values:
                raise ValueError('NH 환경변수 중복 정의')
            values[key.strip()] = value
    if not all(values.get(k) for k in ('NH_KEY', 'NH_SECRET')):
        raise ValueError('.env에 NH_KEY/NH_SECRET 설정이 필요합니다')
    return values


def request(url, body, headers):
    if url != BASE + QUOTE and not url.startswith(BASE + '/oauth2/token?'):
        raise ValueError('허용되지 않은 API')
    # curl uses the system certificate store. No redirects, no verbose logging,
    # and secrets are passed through stdin, never process arguments.
    with tempfile.TemporaryDirectory(prefix='nh-quote-') as tmp:
        header_path = Path(tmp) / 'headers'
        config = ['url = ' + json.dumps(url), 'request = "POST"',
                  'data = ' + json.dumps(body), 'dump-header = ' + json.dumps(str(header_path))]
        config += ['header = ' + json.dumps(k + ': ' + v) for k, v in headers.items()]
        import shutil
        curl = shutil.which('curl')
        if not curl:
            raise RuntimeError('curl 설치가 필요합니다')
        result = subprocess.run([curl, '-q', '--silent', '--show-error',
                                 '--max-time', '40', '--proto', '=https', '--config', '-'],
                                input='\n'.join(config), capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('NH TLS/통신 오류 (자격증명 보호를 위해 원문 생략)')
        lines = header_path.read_text(encoding='utf-8').splitlines()
        status = int(next(s for s in reversed(lines) if s.startswith('HTTP/')).split()[1])
        response_headers = dict((k.lower(), v.strip()) for line in lines
                                for k, sep, v in [line.partition(':')] if sep)
        if status != 200:
            raise RuntimeError('NH HTTP 상태 ' + str(status) + ' (키/토큰 보호를 위해 응답 원문 생략)')
        try:
            return json.loads(result.stdout), response_headers
        except ValueError:
            raise RuntimeError('NH JSON 응답 오류') from None


def token():
    keys = credentials()
    key_hash = hashlib.sha256((keys['NH_KEY'] + '\0' + keys['NH_SECRET']).encode()).hexdigest()
    if CACHE.exists():
        cached = json.loads(CACHE.read_text(encoding='utf-8'))
        if cached.get('key_hash') == key_hash and cached.get('expires_at', 0) > time.time() + 120:
            return cached['access_token']
    query = urlencode(dict(appkey=keys['NH_KEY'], appsecretkey=keys['NH_SECRET'],
                           grant_type='client_credentials', scope='oob'))
    raw, _ = request(BASE + '/oauth2/token?' + query, '',
                     {'Content-Type': 'application/x-www-form-urlencoded'})
    if not isinstance(raw.get('access_token'), str) or not raw['access_token']:
        raise RuntimeError('NH 토큰 발급 응답에 토큰 없음 (원문 비공개)')
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(CACHE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(CACHE, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(dict(access_token=raw['access_token'],
                       key_hash=key_hash,
                       expires_at=time.time() + int(raw.get('expires_in', 86400))), f)
    return raw['access_token']


def fetch(symbol, through, count):
    import re
    from datetime import date
    if not re.fullmatch(r'\d{6}', symbol) or not 2 <= count <= 9999:
        raise ValueError('종목/건수 오류')
    date.fromisoformat(through)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if date.fromisoformat(through) >= datetime.now(ZoneInfo('Asia/Seoul')).date():
        raise ValueError('오늘 이전 완료된 일봉만 조회하세요')
    bearer = token()
    body = {'Input_0': dict(market_cd='KRX', iem_cd=symbol, view_main_yn='Y',
                            gubun='1', edate=through.replace('-', ''),
                            array_cnt=str(count).zfill(4), out1_scale_change='0')}
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + bearer}
    combined, seen, dates = None, set(), {}
    for _ in range(20):
        raw, response_headers = request(BASE + QUOTE, json.dumps(body), headers)
        if not isinstance(raw.get('Output_1'), list) or not raw['Output_1']:
            raise RuntimeError('NH 시세 목록 없음; 정상 시세 응답 확인 실패')
        if raw.get('Output_0', {}).get('iem_cd') != symbol:
            raise RuntimeError('NH 응답 종목 불일치')
        if not str(raw.get('rsp_msg', '')).strip().startswith('조회'):
            raise RuntimeError('미확인 NH 업무 응답; 응답 구조를 검토하세요')
        for row in raw['Output_1']:
            key = row.get('bsop_date')
            if key in dates and dates[key] != row:
                raise RuntimeError('연속 조회 중 동일 날짜 값 변경')
            dates[key] = row
        if combined is None:
            combined = dict(raw)
        combined['Output_1'] = sorted(dates.values(), key=lambda r:r['bsop_date'], reverse=True)[:count]
        if len(dates) >= count or response_headers.get('cts_flag', 'N') != 'Y':
            return combined
        cts = response_headers.get('cts', '')
        if not cts or cts in seen:
            raise RuntimeError('NH 연속조회 키 누락 또는 반복')
        seen.add(cts)
        headers.update(cts=cts, cts_flag='Y')
        time.sleep(1)
    raise RuntimeError('NH 연속조회 한도 초과')
