"""Published PLUG tariff for the reviewed Samsung/KOSPI 2026 example.

Keep fractional won: PLUG-specific settlement rounding was not verified.
Never describe this rate calculation as an account settlement statement.
"""
from decimal import Decimal

PROFILE = {
    'id': 'nh-plug-kospi-2026',
    'label': '나무 PLUG 기본 수수료 · 코스피 2026',
    'commission_rate': 0.0001,
    'sell_transaction_tax_rate': 0.0005,
    'sell_rural_tax_rate': 0.0015,
    'checked_at': '2026-10-10',
    'commission_source': 'https://www.nhplug.com/about-openapi',
    'tax_source': 'https://www.mynamuh.com/WMDoc.action?viewPage=/tx/customerService/chargeInfo.jsp',
    'scope': '삼성전자 005930 · KRX 코스피 · 2026년 거래 · 계좌별 우대 미적용',
    'rounding': '요율 계산값은 원 미만도 유지합니다. API 전용 절사·합산 방식은 미확인으로 실제 정산액과 차이가 날 수 있습니다.',
}


def validate_scope(symbol, start, end):
    if symbol != '005930' or not ('2026-01-01' <= start <= end <= '2026-12-31'):
        raise ValueError('공식 비용 기준은 삼성전자·2026년만 확인했습니다. 다른 종목·연도에 임의 적용하지 않습니다.')


def charges(gross, side):
    gross = Decimal(str(gross))
    if not gross.is_finite() or gross < 0 or side not in ('BUY', 'SELL'):
        raise ValueError('비용 계산 입력 오류')
    commission = gross * Decimal('0.0001')
    tax = gross * Decimal('0.0005') if side == 'SELL' else Decimal(0)
    rural = gross * Decimal('0.0015') if side == 'SELL' else Decimal(0)
    return dict(commission=commission, transaction_tax=tax, rural_tax=rural,
                cost=commission + tax + rural)


def reprice_saved(saved):
    """Reprice the SAME executions; do not claim new AI input or decisions."""
    import copy
    from engine import fingerprint
    if saved.get('source') != 'nh_period' or saved.get('ai_mode') != 'codex-cli':
        raise ValueError('실제 NH 시세와 Codex 판단 기록이 필요합니다. 샘플로 대체하지 않습니다.')
    validate_scope(saved['symbol'], saved['actual_start'], saved['actual_end'])
    out = copy.deepcopy(saved)
    cash, qty = Decimal(str(saved['initial'])), 0
    equity, trades = [], []
    for bar in saved['bars']:
        for old in saved['trades']:
            if old['date'] != bar['date']:
                continue
            gross = Decimal(str(old['price'])) * old['quantity']
            fee = charges(gross, old['side'])
            buy = old['side'] == 'BUY'
            cash += -gross - fee['cost'] if buy else gross - fee['cost']
            qty += old['quantity'] if buy else -old['quantity']
            if cash < 0 or qty < 0:
                raise ValueError('새 비용으로 기존 거래를 유지할 수 없습니다. 설정 화면에서 AI를 다시 실행하세요.')
            trades.append(dict(old, **{k: float(v) for k, v in fee.items()},
                               gross=float(gross), cash_after=float(cash)))
        equity.append(dict(date=bar['date'], value=float(cash + qty * Decimal(str(bar['close']))),
                           cash=float(cash), shares=qty))
    out.update(trades=trades, equity=equity, cash=float(cash), shares=qty,
               final=equity[-1]['value'], cost_profile=PROFILE,
               cost_rate_per_side=PROFILE['commission_rate'],
               calculation_mode='fixed_trades_repriced', original_run_hash=saved['run_hash'],
               original_cost_rate_per_side=saved['cost_rate_per_side'])
    out['profit'] = out['final'] - out['initial']
    out['return_pct'] = out['profit'] / out['initial'] * 100
    out['assumptions'] = [
        '기존 AI 판단·매매일·수량을 고정하고 공식 요율로 비용만 재계산했습니다. 새 현금 상태로 AI를 다시 판단시킨 결과가 아닙니다.',
        '매수·매도 수수료 각각 0.01%, 매도 거래세 0.05%와 농특세 0.15% 별도 반영.',
        PROFILE['rounding'],
        '마지막 날 보유 주식은 종가로 평가합니다. 아직 팔지 않은 주식의 매도 비용은 차감하지 않습니다.',
        '다음 거래일 시가에 모두 체결된다고 가정합니다. 호가·체결 불가·슬리피지·배당·개인별 과세는 재현하지 않습니다.',
        '현재 AI의 과거 재분석이며 미래 지식 유입 가능성이 있습니다. 실제 투자 성과가 아닙니다.']
    out.pop('run_hash', None)
    out['run_hash'] = fingerprint(out)
    return out
