import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
from engine import run
from ai_provider import CodexProvider, fixture_provider

HERE = Path(__file__).parent


def synthetic():
    bars = []
    day = date(2025, 1, 1)
    while day <= date(2026, 9, 30):
        if day.weekday() < 5:
            i = len(bars)
            close = round(55000 + 3500 * math.sin(i / 9) + 1200 * math.sin(i / 3), -1)
            opening = round(close + 220 * math.cos(i / 2), -1)
            bars.append(dict(date=day.isoformat(), open=opening, close=close,
                             high=max(opening, close) + 400, low=min(opening, close) - 400,
                             volume=500000, turnover=close * 500000, corporate_action=False))
        day += timedelta(days=1)
    return dict(source='synthetic', symbol='SAMPLE', name='가상 종목',
                retrieved_at='2026-10-05 synthetic fixture v1', bars=bars)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', type=Path)
    p.add_argument('--cache', type=Path, default=HERE / 'cache', help='AI 기록 폴더; 재실행 검증 시 별도 폴더 사용')
    p.add_argument('--provider', choices=['fixture', 'codex', 'replay'], default='fixture')
    p.add_argument('--start', default='2026-09-14')
    p.add_argument('--end', default='2026-09-25')
    p.add_argument('--initial', default='1000000')
    p.add_argument('--fee', default='0.001')
    p.add_argument('--out', type=Path, default=HERE / 'runs' / 'sample.json')
    args = p.parse_args()
    data = json.loads(args.dataset.read_text(encoding='utf-8')) if args.dataset else synthetic()
    if data['source'] != 'synthetic' and args.provider == 'fixture':
        p.error('NH 실제 가격에는 fixture 판단을 사용하지 않습니다. codex 또는 replay를 선택하세요')
    provider = fixture_provider if args.provider == 'fixture' else CodexProvider(args.cache, args.provider == 'replay')
    result = run(data, args.start, args.end, args.initial, args.fee, provider)
    result['generated_at'] = datetime.now(timezone.utc).isoformat()
    result['ai_mode'] = 'fixture-not-ai' if args.provider == 'fixture' else 'codex-cli'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ['source', 'ai_mode', 'initial', 'final', 'profit', 'run_hash']}, ensure_ascii=False))
    print('signals', len(result['signals']), 'fills', len(result['trades']), 'saved', args.out)


if __name__ == '__main__':
    main()
