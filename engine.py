"""Filming backtest. Pure calculations: no broker, network, or order module."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
import sys

from upstream import strategy

COMMIT = '17f1a9e18aa895f9511ea7297988d512d158be9e'
D = lambda x: Decimal(str(x))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def validate_dataset(data):
    if data.get('source') not in ('synthetic', 'nh_period'):
        raise ValueError('데이터 출처가 필요합니다')
    if not data.get('symbol') or not data.get('retrieved_at'):
        raise ValueError('종목과 조회 시각이 필요합니다')
    previous = ''
    if not data.get('bars'):
        raise ValueError('가격 데이터가 없습니다')
    for b in data['bars']:
        if date.fromisoformat(b['date']).isoformat() != b['date'] or b['date'] <= previous:
            raise ValueError('날짜 중복 또는 정렬 오류')
        for field in ('open', 'high', 'low', 'close', 'volume', 'turnover'):
            if isinstance(b[field], bool) or not math.isfinite(float(b[field])) or float(b[field]) <= 0:
                raise ValueError('가격·거래량·거래대금 누락 또는 비정상 값: ' + field)
        if not b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high']:
            raise ValueError('OHLC 범위가 맞지 않습니다')
        if b.get('corporate_action'):
            raise ValueError('권리락·배당락·분할 자료는 별도 처리 전 사용할 수 없습니다')
        previous = b['date']


def snapshot(data, index, cash, qty, avg):
    b = data['bars'][index]
    cutoff = date.fromisoformat(b['date'])
    past = [r for r in data['bars'][:index + 1]
            if date.fromisoformat(r['date']) >= cutoff - timedelta(days=364)]
    if date.fromisoformat(data['bars'][0]['date']) > cutoff - timedelta(days=364):
        raise ValueError('52주 고가를 계산할 이전 364일 자료가 부족합니다')
    if len(past) < 60:
        raise ValueError('지표 계산용 과거 봉이 부족합니다')
    m = dict(code=data['symbol'], name=data.get('name', data['symbol']),
             price=b['close'], closes=[r['close'] for r in past],
             held=qty > 0, qty=qty, avg=float(avg),
             pnl_pct=float((D(b['close']) / avg - 1) * 100) if avg else 0,
             cash=float(cash), currency='KRW', market='kr', turnover=b['turnover'],
             high_52w=max(r['high'] for r in past), low_52w=min(r['low'] for r in past))
    return dict(date=b['date'], information_through=b['date'], market=m,
                indicators=strategy.facts(m), source=data['source'],
                strategy_commit=COMMIT, instructions=strategy.INSTRUCTIONS,
                limitation='현재 AI의 과거 재분석. 미래 지식 유입을 배제할 수 없음. 공시·뉴스는 입력하지 않음.')


def run(data, start, end, initial, fee, provider):
    validate_dataset(data)
    date.fromisoformat(start); date.fromisoformat(end)
    initial, fee = D(initial), D(fee)
    if not initial.is_finite() or initial <= 0 or not fee.is_finite() or not 0 <= fee < 1:
        raise ValueError('초기 금액 또는 비용률 오류')
    indices = [i for i, b in enumerate(data['bars']) if start <= b['date'] <= end]
    if len(indices) < 2:
        raise ValueError('최소 두 거래일을 선택하세요')
    if any(data['bars'][i].get('dividend_event') for i in indices):
        raise ValueError('평가 기간 내 배당락은 이 간략 예제에서 지원하지 않습니다')
    if start < data['bars'][0]['date'] or end > data['bars'][-1]['date']:
        raise ValueError('요청 기간이 보유 데이터 범위를 벗어납니다')
    cash, qty, avg = initial, 0, D(0)
    trades, signals, equity, pending = [], [], [], None
    for index in indices:
        b = data['bars'][index]
        price = D(b['open'])
        if pending and pending['action'] == 'BUY' and qty == 0:
            amount = min(int((cash / (price * (1 + fee))).to_integral_value(rounding=ROUND_FLOOR)),
                         int(D(strategy.BUY_AMOUNT) // price))
            if amount > 0:
                cost = amount * price * fee
                cash -= amount * price + cost
                qty, avg = amount, price
                trades.append(dict(date=b['date'], side='BUY', price=float(price), quantity=qty,
                                   cost=float(cost), signal_date=pending['date'], reason=pending['reason'],
                                   input_hash=pending['input_hash']))
        elif pending and pending['action'] == 'SELL' and qty:
            cost = qty * price * fee
            cash += qty * price - cost
            trades.append(dict(date=b['date'], side='SELL', price=float(price), quantity=qty,
                               cost=float(cost), signal_date=pending['date'], reason=pending['reason'],
                               input_hash=pending['input_hash']))
            qty, avg = 0, D(0)
        if cash < 0 or qty < 0:
            raise AssertionError('현금/수량 음수')
        value = cash + qty * D(b['close'])
        equity.append(dict(date=b['date'], value=float(value), cash=float(cash), shares=qty))
        snap = snapshot(data, index, cash, qty, avg)
        # Failure is fatal: never silently substitute fake AI or fill missing evidence.
        ai = provider(snap)
        if ai.get('decision') not in ('buy', 'sell', 'hold') or not isinstance(ai.get('reason'), str) or not ai['reason'].strip():
            raise ValueError('AI 판단 형식 오류 또는 판단 누락')
        action, reason = strategy.decide(dict(snap['market'], ai=ai))
        # Clarify the original position rule without changing its decision.
        if action == 'hold' and qty > 0 and ai['decision'] == 'buy':
            reason = '이미 보유 중이어서 원본 전략에 따라 추가 매수하지 않고 보유합니다. AI 원문 판단은 아래에 별도 표시합니다.'
        elif action == 'hold' and qty == 0 and ai['decision'] == 'sell':
            reason = '보유 주식이 없어 매도하지 않습니다. AI 원문 판단은 아래에 별도 표시합니다.'
        pending = dict(date=b['date'], action=action.upper(), reason=reason,
                       ai_decision=ai['decision'], ai_reason=ai['reason'],
                       input_hash=fingerprint(snap), indicators=snap['indicators'],
                       input=snap, provider=ai.get('provider', 'unknown'),
                       executable_next_day=index != indices[-1])
        signals.append(pending)
    final = value
    result = dict(initial=float(initial), final=float(final), profit=float(final - initial),
                  return_pct=float((final / initial - 1) * 100), cash=float(cash), shares=qty,
                  trades=trades, signals=signals, equity=equity,
                  bars=[data['bars'][i] for i in indices], source=data['source'],
                  symbol=data['symbol'], name=data.get('name'), retrieved_at=data['retrieved_at'],
                  requested_start=start, requested_end=end, actual_start=equity[0]['date'],
                  actual_end=equity[-1]['date'], cost_rate_per_side=float(fee), buy_amount=strategy.BUY_AMOUNT,
                  strategy_commit=COMMIT, dataset_hash=fingerprint(data),
                  assumptions=['하루 한 번 종가 판단 → 다음 거래일 시가 가상 체결',
                               '1종목 · 정수 수량 · 매수 예산 30만 원 · 비용은 별도 가정',
                               '마지막 날 미청산 보유분은 종가 평가 · 마지막 판단 미체결',
                               '배당·세금 별도 계산·슬리피지·시장충격·체결 불가 상황 미반영',
                               '현재 AI 재분석에는 미래 지식 유입 가능 · 실제 투자 성과 아님'])
    result['run_hash'] = fingerprint(result)
    return result
