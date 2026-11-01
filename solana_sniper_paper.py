#!/usr/bin/env python3
"""Sniper Solana PAPER ONLY, Python 3.10+, standard library.

Run: python3 solana_sniper_paper.py --demo
     python3 solana_sniper_paper.py --self-test
     python3 solana_sniper_paper.py --stdin < events.jsonl
No network client, wallet, key, signing or transaction submission exists here.
Not a live market backtest. Demo tokens/prices and cost inputs are SYNTHETIC.

JSONL candidate event keys: type='candidate', mint (identifier), chain='solana',
age_minutes, age_source='mint_creation', liquidity_usd, volume_5m_usd,
buys_5m, sells_5m, mint_revoked=true, freeze_revoked=true,
now (Unix seconds), observed_at, price (USD). Missing/invalid data is rejected.
Price event: type='price', mint, price, now, observed_at.
Prices must be positive, fresh and arrive in time order. Same mint cannot reenter.

Fixed strategy: age 1..60 min, LP>=10000, vol5m>=1500, buys5m>=12,
BUY/SELL count ratio>=1.5, authorities revoked, $5 per entry,
TP +20%, SL -10% measured from simulated entry fill, max 2 positions.
Slippage is an ASSUMED adverse fill, not guaranteed execution or an order cap.
Default fee 1%/side, fixed cost $0.05/side, slippage 0bp are assumptions,
not measured current platform fees. Change CLI inputs for stress scenarios.
Token account deposits, DEX fees and failed tx costs require additional models.
Marks crossing TP/SL trigger a simulated full exit at that mark, including gaps.
No guarantee a real token can sell. Mint/freeze checks alone cannot prove safety.

Cloud next steps: new worker + durable DB; discovery feed; fresh 5-minute
metrics; RPC authority/Token-2022 checks; quote/sellability validation; costs;
atomic position reservations; stale-feed pause and alerts. Persist state before
restart. This version is finite/offline and has NO live trading switch.
"""
import argparse
import json
import math
import sys


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class PaperBot:
    def __init__(self, fee=0.01, fixed=0.05, slippage_bps=0):
        if not (0 <= fee < 1 and fixed >= 0 and 0 <= slippage_bps < 10000):
            raise ValueError('Invalid cost assumptions')
        self.fee, self.fixed, self.slip = fee, fixed, slippage_bps / 10000
        self.positions, self.seen, self.pnl = {}, set(), 0.0
        self.clock = -math.inf

    def process(self, e):
        mint = e.get('mint')
        def result(action, reasons=None, **extra):
            return dict(mode='PAPER', mint=mint, action=action,
                        reasons=reasons or [], positions=len(self.positions), **extra)
        now, stamp, price = e.get('now'), e.get('observed_at'), e.get('price')
        if not all(number(v) for v in (now, stamp, price)) or price <= 0:
            return result('REJECT', ['invalid_price_or_timestamp'])
        if now < self.clock or not 0 <= now - stamp <= 30:
            return result('REJECT', ['stale_or_out_of_order'])
        self.clock = now
        if not isinstance(mint, str) or not mint:
            return result('REJECT', ['missing_mint'])
        if e.get('type') == 'price':
            p = self.positions.get(mint)
            if not p:
                return result('IGNORE')
            change = price / p['entry'] - 1
            if change < .20 - 1e-12 and change > -.10 + 1e-12:
                return result('HOLD')
            gross = p['quantity'] * price * (1 - self.slip)
            proceeds = gross * (1 - self.fee) - self.fixed
            pnl = proceeds - p['cost']
            self.pnl += pnl
            del self.positions[mint]
            return result('PAPER_SELL', trigger='TP' if change >= .20 - 1e-12 else 'SL',
                          net_pnl_usd=round(pnl, 6))
        if e.get('type') != 'candidate':
            return result('REJECT', ['unknown_event_type'])
        reasons = []
        if e.get('chain') != 'solana':
            reasons.append('wrong_chain')
        if e.get('age_source') != 'mint_creation':
            reasons.append('mint_age_unverified')
        checks = [('age_minutes', 1, 60), ('liquidity_usd', 10000, math.inf),
                  ('volume_5m_usd', 1500, math.inf), ('buys_5m', 12, math.inf)]
        for key, low, high in checks:
            if not number(e.get(key)) or not low <= e[key] <= high:
                reasons.append(key)
        buys, sells = e.get('buys_5m'), e.get('sells_5m')
        if not all(number(v) and v >= 0 and int(v) == v for v in (buys, sells)):
            reasons.append('invalid_trade_counts')
        elif sells > 0 and buys / sells < 1.5:
            reasons.append('buy_sell_ratio')
        for key in ('mint_revoked', 'freeze_revoked'):
            if e.get(key) is not True:
                reasons.append(key)
        if mint in self.seen:
            reasons.append('duplicate_mint')
        if len(self.positions) >= 2:
            reasons.append('max_2_positions')
        if reasons:
            return result('REJECT', reasons)
        entry = price * (1 + self.slip)
        self.positions[mint] = dict(entry=entry, quantity=5 / entry,
                                    cost=5 + 5 * self.fee + self.fixed)
        self.seen.add(mint)
        return result('PAPER_BUY', amount_usd=5)


def candidate(mint='SYNTHETIC_A', **overrides):
    e = dict(type='candidate', mint=mint, chain='solana', age_minutes=10,
             age_source='mint_creation', liquidity_usd=12000, volume_5m_usd=1800,
             buys_5m=18, sells_5m=12, mint_revoked=True, freeze_revoked=True,
             now=1000, observed_at=1000, price=1)
    e.update(overrides)
    return e


def demo():
    return [candidate('SYNTHETIC_OLD', age_minutes=61),
            candidate('SYNTHETIC_LOW_VOLUME', volume_5m_usd=1499),
            candidate('SYNTHETIC_WEAK_RATIO', buys_5m=17),
            candidate('SYNTHETIC_UNKNOWN_SECURITY', mint_revoked=None),
            candidate('SYNTHETIC_A'), candidate('SYNTHETIC_B'),
            candidate('SYNTHETIC_C'),
            dict(type='price', mint='SYNTHETIC_A', price=1.20, now=1001, observed_at=1001),
            dict(type='price', mint='SYNTHETIC_B', price=.90, now=1001, observed_at=1001)]


def self_test():
    for age in (1, 60):
        assert PaperBot().process(candidate(age_minutes=age))['action'] == 'PAPER_BUY'
    for age in (0, 61):
        assert PaperBot().process(candidate(age_minutes=age))['action'] == 'REJECT'
    for fields in (dict(age_source='pool_creation'), dict(mint_revoked=None),
                   dict(freeze_revoked=False), dict(volume_5m_usd=1499),
                   dict(buys_5m=11), dict(buys_5m=17), dict(liquidity_usd=9999),
                   dict(observed_at=969), dict(price=float('nan'))):
        assert PaperBot().process(candidate(**fields))['action'] == 'REJECT', fields
    b = PaperBot()
    results = [b.process(e) for e in demo()]
    assert results[6]['reasons'] == ['max_2_positions']
    assert results[7]['trigger'] == 'TP' and results[7]['net_pnl_usd'] == .79
    assert results[8]['trigger'] == 'SL' and results[8]['net_pnl_usd'] == -.695
    assert not b.positions and abs(b.pnl - .095) < 1e-10
    assert b.process(candidate(now=1002, observed_at=1002))['reasons'] == ['duplicate_mint']
    assert b.process(candidate('NEXT', now=999, observed_at=999))['action'] == 'REJECT'
    print('PASS: age boundaries, missing security, stale data, thresholds, position cap, TP/SL, costs, deduplication')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--demo', action='store_true')
    mode.add_argument('--stdin', action='store_true')
    mode.add_argument('--self-test', action='store_true')
    p.add_argument('--fee', type=float, default=.01)
    p.add_argument('--fixed-cost-usd', type=float, default=.05)
    p.add_argument('--slippage-bps', type=float, default=0)
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        bot = PaperBot(args.fee, args.fixed_cost_usd, args.slippage_bps)
        events = demo() if args.demo else (json.loads(line) for line in sys.stdin if line.strip())
        for event in events:
            print(json.dumps(bot.process(event)))
        print(json.dumps(dict(mode='PAPER', data='SYNTHETIC' if args.demo else 'USER_INPUT',
                              realized_pnl_usd=round(bot.pnl, 6), open_positions=len(bot.positions),
                              fee_per_side=args.fee, assumed_fixed_usd_per_side=args.fixed_cost_usd,
                              assumed_slippage_bps=args.slippage_bps)))
