"""Read-only NH historical quote import. Auth is isolated in nh_client.py."""
import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler
from engine import validate_dataset, fingerprint

URL = 'https://api.nhplug.com:8443/krstock/quote/v1/period'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('인증 헤더 유출 방지를 위해 리다이렉트 금지')


def normalize(raw, symbol, retrieved_at, through, success_code=None, reviewed=False):
    if not reviewed:
        raise ValueError('완결 일봉 종가·단위·권리처리 검토 확인이 필요합니다')
    if not re.fullmatch(r'\d{6}', symbol):
        raise ValueError('국내 6자리 종목코드 필요')
    date.fromisoformat(through)
    msg = raw.get('message') or {}
    if success_code and msg.get('msg_code') != success_code:
        raise ValueError('NH 업무 응답 코드가 확인된 성공 코드와 다릅니다')
    if not success_code and raw.get('rsp_msg') != '조회가 완료되었습니다.':
        raise ValueError('미확인 NH 업무 응답; 구조 확인 필요')
    if raw.get('Output_0', {}).get('iem_cd') != symbol:
        raise ValueError('응답 종목코드 불일치')
    rows = raw.get('Output_1')
    if not isinstance(rows, list) or not rows:
        raise ValueError('NH 과거 가격 목록이 없습니다')
    bars = []
    for r in rows:
        d = datetime.strptime(r['bsop_date'], '%Y%m%d').date().isoformat()
        if d > through:
            continue
        ex = str(r.get('flng_cls_code', '')).strip().zfill(2)
        split = str(r.get('fcam_mod_cls_code', '')).strip().zfill(2)
        # Known cash-dividend ex-dates may appear only in the indicator warmup.
        # Actual evaluation periods containing them fail closed in engine.run.
        action = ex not in ('00', '02', '05') or split != '00'
        b = dict(date=d, corporate_action=action, dividend_event=ex in ('02','05'),
                 ex_code=ex, split_code=split)
        for target, source in [('open', 'stck_oprc'), ('high', 'stck_hgpr'), ('low', 'stck_lwpr'),
                               ('close', 'stck_prpr'), ('volume', 'vol'), ('turnover', 'tr_pbmn')]:
            b[target] = float(str(r[source]).replace(',', ''))
        bars.append(b)
    data = dict(source='nh_period', symbol=symbol, name=raw['Output_0'].get('iem_nm', symbol),
                retrieved_at=retrieved_at, bars=sorted(bars, key=lambda b: b['date']),
                raw_response_hash=fingerprint(raw), historical_fields_reviewed=True,
                source_url='https://www.nhplug.com/openapi-docs/krstock/openapi.json')
    validate_dataset(data)
    return data


def fetch(symbol, through, count):
    from nh_client import fetch as read_only_fetch
    return read_only_fetch(symbol, through, count)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--response', type=Path, help='저장된 NH 기간별 시세 응답 JSON')
    p.add_argument('--fetch', action='store_true')
    p.add_argument('--symbol', required=True)
    p.add_argument('--through', required=True, help='완료된 거래일 YYYY-MM-DD')
    p.add_argument('--count', type=int, default=500)
    p.add_argument('--success-code', help='구형 message.msg_code 응답에만 지정')
    p.add_argument('--reviewed-historical-fields', action='store_true')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if bool(a.response) == a.fetch:
        p.error('--response 또는 --fetch 중 하나를 지정하세요')
    if not a.reviewed_historical_fields:
        p.error('stck_prpr의 완결 일봉 종가 의미·원 단위·권리처리 확인 후 실행하세요')
    # Do not accept an intraday current bar as the completed daily close.
    from zoneinfo import ZoneInfo
    if date.fromisoformat(a.through) >= datetime.now(ZoneInfo('Asia/Seoul')).date():
        p.error('오늘 이전의 완료된 거래일을 사용하세요')
    raw = fetch(a.symbol, a.through, a.count) if a.fetch else json.loads(a.response.read_text())
    data = normalize(raw, a.symbol, datetime.now(timezone.utc).isoformat(), a.through,
                     a.success_code, a.reviewed_historical_fields)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print('기간별 시세 저장:', len(data['bars']), '봉. 계좌 조회·주문 호출 없음.')


if __name__ == '__main__':
    main()
