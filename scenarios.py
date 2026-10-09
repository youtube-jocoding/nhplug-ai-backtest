"""User-selected experiments; no orders, credentials, or network calls."""
from datetime import date, timedelta
from upstream import strategy

DEFAULTS = dict(initial=1000000, buy_amount=300000, stop_loss=5, take_profit=10,
                short_days=5, long_days=20, rsi_buy=70, rsi_sell=75,
                high_limit=95, min_turnover=100, use_ma=True, use_macd=True,
                use_rsi=True, use_high=True, use_turnover=True,
                start='2026-09-14', end='2026-09-23',
                prompt='원금을 지키는 것을 우선해 줘. 켜진 조건을 충족해도 상승 근거가 약하면 기다려 줘. 판단 이유에는 실제로 본 숫자를 쓰고, 중학생도 이해할 수 있는 말로 설명해 줘.')


def parse(values):
    import math
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError('설정 항목을 확인하세요.')
    c = dict(DEFAULTS, **values)
    if not isinstance(c['prompt'], str) or not c['prompt'].strip() or len(c['prompt']) > 4000:
        raise ValueError('AI에게 줄 지침을 1~4,000자로 적어 주세요.')
    limits = {'initial': (1, 1000000000), 'buy_amount': (1, 1000000000),
              'stop_loss': (.1, 99), 'take_profit': (.1, 1000),
              'short_days': (2, 120), 'long_days': (3, 250),
              'rsi_buy': (0, 100), 'rsi_sell': (0, 100),
              'high_limit': (1, 100), 'min_turnover': (0, 1000000)}
    for key, (lo, hi) in limits.items():
        try:
            if isinstance(c[key], bool):
                raise ValueError()
            n = float(c[key])
            if not math.isfinite(n) or not lo <= n <= hi:
                raise ValueError()
            if key in ('initial', 'buy_amount', 'short_days', 'long_days'):
                if not n.is_integer():
                    raise ValueError()
                n = int(n)
            c[key] = n
        except (ValueError, TypeError):
            raise ValueError(f'{key}: {lo}~{hi} 범위의 숫자가 필요합니다.') from None
    for key in ('use_ma', 'use_macd', 'use_rsi', 'use_high', 'use_turnover'):
        if not isinstance(c[key], bool):
            raise ValueError('조건 켜기·끄기 값이 올바르지 않습니다.')
    if c['short_days'] >= c['long_days']:
        raise ValueError('짧은 평균 기간은 긴 평균 기간보다 작아야 합니다.')
    try:
        start, end = date.fromisoformat(c['start']), date.fromisoformat(c['end'])
        if start >= end or start.year != 2026 or end.year != 2026:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('2026년 안에서 시작일보다 늦은 종료일을 선택하세요.') from None
    return c


def measurements(m, c):
    closes = m['closes']
    a, b = strategy.macd(closes)
    return dict(short=strategy.moving_average(closes, c['short_days']),
                long=strategy.moving_average(closes, c['long_days']),
                rsi=strategy.rsi(closes), macd=a - b if a is not None else None)


def checks(m, c):
    v = measurements(m, c)
    rows = [
        ('평균선 위', c['use_ma'], v['short'] is not None and v['long'] is not None and m['price'] > v['short'] and m['price'] > v['long'],
         f"종가 {m['price']:,.0f}원 / {c['short_days']}일 평균 {v['short']} / {c['long_days']}일 평균 {v['long']}"),
        ('MACD 상승 흐름', c['use_macd'], v['macd'] is not None and v['macd'] > 0, f"MACD 차이 {v['macd']} > 0"),
        ('RSI 과열 피하기', c['use_rsi'], v['rsi'] is not None and v['rsi'] <= c['rsi_buy'], f"RSI {v['rsi']} ≤ {c['rsi_buy']}"),
        ('1년 최고가 근처 피하기', c['use_high'], bool(m['high_52w']) and m['price'] < m['high_52w'] * c['high_limit'] / 100,
         f"종가 {m['price']:,.0f}원 < 최고가의 {c['high_limit']}%"),
        ('거래대금 확인', c['use_turnover'], m['turnover'] >= c['min_turnover'] * 100000000,
         f"하루 {m['turnover']/100000000:,.2f}억 원 ≥ {c['min_turnover']:g}억 원")]
    return [dict(label=label, enabled=enabled, passed=bool(passed), detail=detail) for label, enabled, passed, detail in rows]


def instructions(c):
    return ('과거 자료만으로 buy/sell/hold를 정하고 수치를 들어 쉬운 한국어로 설명하라. '
            '켜진 매수 조건을 모두 만족할 때만 매수를 검토하고 애매하면 hold. '
            f"평균선 조건 {'켜짐' if c['use_ma'] else '꺼짐'}: 종가 > {c['short_days']}일 및 {c['long_days']}일 평균. "
            f"MACD 조건 {'켜짐' if c['use_macd'] else '꺼짐'}: MACD-신호선 > 0. "
            f"RSI 조건 {'켜짐' if c['use_rsi'] else '꺼짐'}: 매수 RSI ≤ {c['rsi_buy']}, 매도 RSI > {c['rsi_sell']}. "
            f"고점 제한 {'켜짐' if c['use_high'] else '꺼짐'}: 종가 < 52주 최고가의 {c['high_limit']}%. "
            f"거래대금 제한 {'켜짐' if c['use_turnover'] else '꺼짐'}: 하루 {c['min_turnover']}억 원 이상. "
            '매도 흐름 조건은 켜진 평균선·MACD 조건이 모두 하락일 때이며 둘 다 꺼져 있으면 이 조건은 쓰지 않는다. '
            f"손절 -{c['stop_loss']}%, 익절 +{c['take_profit']}%, 한 번 매수 예산 {c['buy_amount']}원, 추가매수 금지. "
            '꺼진 조건을 이유로 거래를 막지 마라. 오늘 종가 판단 후 다음 거래일 시가 가상 체결이다. '
            '다음은 사용자가 이번 실험에 지정한 판단 지침이다. 매수 예산·추가매수 금지·손절·익절 및 켜진 고점·거래대금 제한은 코드가 적용한다. '
            + c['prompt'])


def decide(m, ai, c):
    if m['held']:
        if m['pnl_pct'] <= -c['stop_loss']:
            return 'sell', f"산 가격 대비 {m['pnl_pct']:+.2f}%로 손절 −{c['stop_loss']:g}% 기준에 도달했습니다. 다음 거래일에 전부 팝니다."
        if m['pnl_pct'] >= c['take_profit']:
            return 'sell', f"산 가격 대비 {m['pnl_pct']:+.2f}%로 익절 +{c['take_profit']:g}% 기준에 도달했습니다. 다음 거래일에 전부 팝니다."
        return ('sell', ai['reason']) if ai['decision'] == 'sell' else ('hold', '보유 중에는 더 사지 않습니다. ' + ai['reason'])
    for row in checks(m, c)[3:]:
        if row['enabled'] and not row['passed']:
            return 'hold', row['label'] + ' 제한에 걸려 사지 않습니다. ' + row['detail']
    return ('buy', ai['reason']) if ai['decision'] == 'buy' else ('hold', ai['reason'])


def validate_experiment(data, c):
    from engine import validate_dataset, snapshot
    from costs import validate_scope
    from decimal import Decimal
    validate_dataset(data)
    validate_scope(data['symbol'], c['start'], c['end'])
    if data['source'] != 'nh_period':
        raise ValueError('저장된 NH 실제 주가가 필요합니다. 샘플로 대체하지 않습니다.')
    if c['start'] < data['bars'][0]['date'] or c['end'] > data['bars'][-1]['date']:
        raise ValueError('저장된 주가 범위 밖입니다. 화면에 표시된 기간 안에서 선택하세요.')
    indices = [i for i, b in enumerate(data['bars']) if c['start'] <= b['date'] <= c['end']]
    if len(indices) < 2:
        raise ValueError('최소 2거래일을 선택하세요.')
    if any(data['bars'][i].get('dividend_event') for i in indices):
        raise ValueError('배당락이 포함된 기간은 아직 지원하지 않습니다.')
    s = snapshot(data, indices[0], Decimal(c['initial']), 0, Decimal(0))
    if c['use_ma'] and measurements(s['market'], c)['long'] is None:
        raise ValueError('선택한 평균 기간에 필요한 과거 가격이 부족합니다.')
