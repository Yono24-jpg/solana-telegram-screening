"""Explain existing gates without changing eligibility. Internal research only."""
import copy
from collections import Counter
import hunter_modes
import market_data as market
from screening_rules import number, address


def evaluate(pool, history, now, narrative):
    rows = []
    def check(name, value, rule, test):
        valid = value is not None
        try: status = ('pass' if test(value) else 'fail') if valid else 'unknown'
        except (TypeError, ValueError, ZeroDivisionError, OverflowError): status = 'unknown'
        rows.append({'gate': name, 'status': status, 'observed': value, 'rule': rule})
    def numeric(path):
        value = market.get(pool, path)
        # Match the actual gates: strings are accepted only for priceUsd.
        return market.amount(value) if path == 'priceUsd' else value if number(value) else None
    mint = market.get(pool, 'baseToken.address'); pair = pool.get('pairAddress')
    check('identity', bool(pool.get('chainId') == 'solana' and address(pair) and address(mint)), 'Solana and valid mint/pair', bool)
    for flag in ('identityConflict', 'valuationConflict', 'ageConflict'):
        check(flag, bool(pool.get(flag)), 'must be false', lambda x: not x)
    created = numeric('pairCreatedAt'); age = now-created/1000 if created is not None else None
    check('age_seconds', age, '60..7776000', lambda x: 60 <= x <= hunter_modes.MAX_AGE)
    cap = numeric('marketCap'); lp = numeric('liquidity.usd'); vol = numeric('volume.m5')
    buys = numeric('txns.m5.buys'); sells = numeric('txns.m5.sells')
    m5 = numeric('priceChange.m5'); h1 = numeric('priceChange.h1'); h24 = numeric('priceChange.h24')
    check('circulating_cap', cap, '20000..5000000; no FDV substitution', lambda x: 20000 <= x <= 5000000)
    check('volume_h1', numeric('volume.h1'), '>=5000 USD', lambda x: x >= 5000)
    check('liquidity_usd', lp, '>=10000 USD', lambda x: x >= 10000)
    check('liquidity_cap_ratio', lp/cap if lp is not None and cap is not None and cap > 0 else None, '>=0.08', lambda x: x >= .08)
    check('volume_m5', vol, '>=1500 USD', lambda x: x >= 1500)
    check('buys_m5', buys, 'integer >=12', lambda x: x >= 12 and x == int(x))
    check('sells_m5', sells, 'integer >=0', lambda x: x >= 0 and x == int(x))
    check('buy_sell_ratio', buys/max(sells, 1) if buys is not None and sells is not None else None, '>=1.5', lambda x: x >= 1.5)
    check('price_usd', numeric('priceUsd'), '>0', lambda x: x > 0)
    check('price_change_m5', m5, '0..25 percent; anti-chase', lambda x: 0 <= x <= 25)
    check('price_change_h1', h1, '-15..80 percent and required by v5', lambda x: -15 <= x <= 80)
    check('price_change_h24', h24, '<=200 percent and required by v5', lambda x: x <= 200)
    eligible = [r for r in (history.get(pair, []) if isinstance(history, dict) else []) if isinstance(r, dict)
                and r.get('mint') == mint and all(number(r.get(k)) for k in ('t','price','lp','volume','buys','sells'))
                and 300 <= now-r['t'] <= 900 and min(r['price'],r['lp'],r['volume'],r['buys']) > 0 and r['sells'] >= 0]
    if eligible:
        old = max(eligible, key=lambda r:r['t']); price = numeric('priceUsd')
        check('historical_lp_retained', lp/old['lp'] if lp is not None else None, '>=0.90', lambda x:x >= .9)
        check('historical_price_change', 100*(price/old['price']-1) if price is not None else None, '-5..25 percent', lambda x:-5 <= x <= 25)
    else:
        rows += [{'gate': name, 'status': 'not_applicable', 'observed': None, 'rule': 'no eligible 5–15 minute history'}
                 for name in ('historical_lp_retained','historical_price_change')]
    # Counterfactual only removes the narrative rejection to expose market result;
    # it never changes the decision passed to the real delivery pipeline.
    without_narrative = dict(narrative, reject=None)
    market_result = hunter_modes.assess(pool, history, now, without_narrative)
    decision = hunter_modes.assess(pool, history, now, narrative)
    score=None; growth=None
    if all(number(v) for v in (cap,lp,vol,buys,sells,m5)) and cap>0 and buys+sells>0:
        acceleration=0
        if eligible:
            old=max(eligible,key=lambda r:r['t'])
            growth=min(vol/old['volume'],buys/old['buys'],(buys+sells)/(old['buys']+old['sells']))
            acceleration=10*min(1,max(0,growth-1)/.5)
        score=round(25*min(1,max(0,(buys/(buys+sells)-.5)/.25))+20*min(1,buys/40)
                    +20*min(1,lp/cap/.15)+15*min(1,vol/6000)+10*max(0,1-m5/30)+acceleration,1)
    check('market_score',score,'>=60; existing formula',lambda x:x>=60)
    mode=None
    if age is not None and cap is not None:
        early=age<=86400 and cap<=500000
        viral=False
        if eligible and all(number(v) for v in (vol,buys,sells)):
            old=max(eligible,key=lambda r:r['t'])
            viral=vol/old['volume']>=1.5 and buys/old['buys']>=1.2 and (buys+sells)/(old['buys']+old['sells'])>=1.2
        mode=early or viral or narrative.get('relationship')=='possible_name_parody'
    check('hunter_mode',mode,'EARLY, VIRAL or PARODY mode',bool)
    narrative_known=narrative.get('reject')!='historical_narrative_not_archived'
    check('narrative',not bool(narrative.get('reject')) if narrative_known else None,'existing verified narrative relationship',bool)
    return {'pair':pair, 'mint':mint, 'age_seconds':age, 'primary_rejection':decision.get('reject'),
            'market_rejection':market_result.get('reject'), 'market_pass':not market_result.get('reject'),
            'checks':rows, 'failed':[r['gate'] for r in rows if r['status']=='fail'],
            'unknown':[r['gate'] for r in rows if r['status']=='unknown'],
            'security_stage':'not_reached' if decision.get('reject') else 'pending',
            'internal_only':True, 'verified_alert':False}


def summary(rows):
    statuses = {}
    for row in rows:
        for c in row['checks']:
            bucket = statuses.setdefault(c['gate'], Counter()); bucket[c['status']] += 1
    return {'pools':len(rows),'gate_statuses':{k:dict(v) for k,v in statuses.items()},
            'primary_rejections':dict(Counter(r['primary_rejection'] or 'market_and_narrative_pass' for r in rows)),
            'market_pass':sum(r['market_pass'] for r in rows),
            'reaches_security':sum(r['security_stage']!='not_reached' for r in rows),
            'independent_failed_checks':sum(len(r['failed']) for r in rows),
            'unknown_checks':sum(len(r['unknown']) for r in rows),
            'scope':'overlapping independent gate diagnostics; not additional eligibility rules'}


def observe_research(state, pool, audit, narrative, now):
    """Potential market leads need no invented narrative; never sent to Telegram."""
    age = audit['age_seconds']; lp = market.amount(market.get(pool,'liquidity.usd'))
    volume = market.amount(market.get(pool,'volume.m5')); buys = market.amount(market.get(pool,'txns.m5.buys'))
    if not number(age) or not 60 <= age <= 3600 or lp is None or lp < 10000 or volume is None or volume < 1500 or buys is None or buys < 12:
        return
    r = state.setdefault('market_research_v54', {'at':now,'rows':{}}); r['at']=now
    r['rows'][audit['pair']]={'at':now,'mint':audit['mint'],'pair':audit['pair'],'tier':'INTERNAL MARKET WATCH',
        'primary_rejection':audit['primary_rejection'],'failed':audit['failed'],'unknown':audit['unknown'],
        'narrative':narrative.get('label'),'security_verified':False,'internal_only':True}
    r['rows']=dict(sorted(((k,v) for k,v in r['rows'].items() if 0 <= now-v['at'] <= 86400),key=lambda x:-x[1]['at'])[:200])


def gainer_review(state, pools, audits, now):
    """Observed/provider-reported rises are not evidence of a missed safe trade."""
    by_pair={r['pair']:r for r in audits}; candidates=[]
    for p in pools:
        lp=market.amount(market.get(p,'liquidity.usd')); h1=market.amount(market.get(p,'priceChange.h1'))
        if lp is None or lp<10000 or h1 is None or h1<50: continue
        mint=market.get(p,'baseToken.address');pair=p.get('pairAddress');a=by_pair.get(pair,{})
        historical=[r for r in state.get('memory_v5',{}).values() if r.get('pair')==pair and r.get('mint')==mint and r.get('at',now+1)<now-120]
        first=min(historical,key=lambda r:r['at']) if historical else None
        candidates.append({'pair':pair,'mint':mint,'provider_h1_change_pct':h1,'liquidity_usd':lp,
            'current_primary_rejection':a.get('primary_rejection'),'current_failed':a.get('failed',[]),
            'seen_before':bool(first),'first_recorded_at':first.get('at') if first else None,
            'initial_recorded_rejection':first.get('initial_decision') if first else None,
            'initial_safety_complete':first.get('initial_safety_complete',False) if first else False,
            'classification':'provider_reported_rise; safe missed opportunity unproven',
            'url':'https://dexscreener.com/solana/'+pair})
    # Historical extreme jumps are quarantined, rather than counted as proven winners.
    old=[r for r in state.get('memory_v5',{}).values() if r.get('best_observed_pct',0)>=50]
    return {'provider_reported_risers':sorted(candidates,key=lambda r:-r['provider_h1_change_pct'])[:20],
            'historical_observed_rises':len(old),'historical_extreme_unverified':sum(r.get('best_observed_pct',0)>1000 for r in old),
            'proved_missed_safe_trades':None,
            'scope':'selection-biased provider/forward observations; no independent historical safety, liquidity or executed-return proof'}


def replay(rows):
    """Frozen snapshots, v5.3 decision parity and richer v5.4 explanations."""
    audited=[]
    for row in rows:
        pool=row['pool'];now=row['observed_at'];history=row.get('history',{});n=row.get('narrative',{'reject':'historical_narrative_not_archived'})
        old=hunter_modes.assess(copy.deepcopy(pool),history,now,n)
        new=evaluate(pool,history,now,n)
        audited.append(new)
        if old.get('reject')!=new['primary_rejection']:raise ValueError('eligibility_parity_failed')
    out=summary(audited)
    out.update(decision_parity=True,old_primary_reason_count=sum(bool(r['primary_rejection']) for r in audited),
               new_check_count=sum(len(r['checks']) for r in audited),security_relaxed=False,
               scope='same frozen observations; diagnostic gain only, no invented historical safety or profit')
    return out
