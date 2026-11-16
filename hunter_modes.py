"""Shared market gates for all v5 modes. No FDV substitution or safety exceptions."""
from screening_rules import market, number
MAX_AGE = 90*86400


def assess(pool, history, now, narrative):
    try:
        cap=pool['marketCap']; age=now-pool['pairCreatedAt']/1000
        h1=pool['volume']['h1']; tx=pool['txns']['m5']
        if not all(number(x) for x in (cap,age,h1,tx['buys'],tx['sells'])): return {'reject':'v5_market_missing'}
        if not 60<=age<=MAX_AGE: return {'reject':'v5_pool_age'}
        if not 20000<=cap<=5000000: return {'reject':'v5_market_cap'}
        if h1<5000: return {'reject':'v5_volume_h1'}
        if pool.get('ageConflict'): return {'reject':'v5_age_conflict'}
        result=market(pool,history,now,max_age=MAX_AGE)
        if result.get('reject'): return result
        # Unknown price windows cannot bypass the anti-chase gate.
        if not number(result.get('h1')) or not number(result.get('h24')): return {'reject':'v5_price_windows_missing'}
        modes=[]
        if age<=86400 and cap<=500000: modes.append('EARLY HUNTER')
        growth=result.get('growth')
        if growth and growth['volume']>=1.5 and growth['buys']>=1.2 and growth['transactions']>=1.2:
            modes.append('VIRAL HUNTER')
        if narrative.get('relationship')=='possible_name_parody': modes.append('PARODY HUNTER')
        if not modes: return {'reject':'v5_viral_acceleration_unverified'}
        if narrative.get('reject'): return {'reject':narrative['reject']}
        result['modes']=modes
        return result
    except (KeyError,TypeError,ValueError,ZeroDivisionError): return {'reject':'v5_market_missing'}


def scores(narrative, market, safety, social, buyers):
    # Unknown social/virality stays None, rather than being interpreted as zero risk.
    sources=narrative.get('publisher_count',0)
    return {'narrative':narrative.get('score'), 'virality':narrative.get('virality_score'),
            'momentum':market.get('score'), 'community':social.get('score'),
            'security':safety.get('score') if safety.get('complete') else None,
            'evidence_quality':min(100, sources*10+30*bool(safety.get('complete'))+20*bool(buyers.get('strong'))+20*bool(social.get('complete')))}
