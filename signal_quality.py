"""Transparent, rule-based early momentum checks; no prediction model."""
import math

MIN_COMPARISON_SECONDS=300
MAX_COMPARISON_SECONDS=900
HISTORY_TTL=1800
MAX_PAIRS=200
MAX_SNAPSHOTS=12
MIN_SCORE=70

def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def snapshot(pool, now):
    try:
        if not finite(now): return None
        pair=pool['pairAddress']; mint=pool['baseToken']['address']
        if pool['chainId']!='solana' or not isinstance(pair,str) or not pair or not isinstance(mint,str) or not mint:
            return None
        raw_price=pool['priceUsd']
        if isinstance(raw_price,bool): return None
        price=float(raw_price)
        lp=pool['liquidity']['usd']; vol=pool['volume']['m5']
        buys=pool['txns']['m5']['buys']; sells=pool['txns']['m5']['sells']
        if not all(finite(v) for v in (price,lp,vol,buys,sells)):
            return None
        if min(price,lp)<=0 or min(vol,buys,sells)<0 or int(buys)!=buys or int(sells)!=sells:
            return None
        return {'t':now,'mint':mint,'price':price,'lp':lp,'volume':vol,'buys':buys,'sells':sells}
    except (KeyError,TypeError,ValueError,OverflowError):
        return None

def valid_record(row, now):
    if not isinstance(row,dict) or not isinstance(row.get('mint'),str): return False
    if not all(finite(row.get(k)) for k in ('t','price','lp','volume','buys','sells')): return False
    return (0<=now-row['t']<=HISTORY_TTL and row['price']>0 and row['lp']>0
            and min(row['volume'],row['buys'],row['sells'])>=0
            and int(row['buys'])==row['buys'] and int(row['sells'])==row['sells'])

def merge_observations(*histories, now):
    """Bound persisted public market history and merge by timestamp."""
    merged={}
    for history in histories:
        if not isinstance(history,dict): continue
        for pair,rows in history.items():
            if not isinstance(pair,str) or not isinstance(rows,list): continue
            dest=merged.setdefault(pair,{})
            for row in rows:
                if valid_record(row,now):
                    dest[(row['t'],row['mint'])]={k:row[k] for k in ('t','mint','price','lp','volume','buys','sells')}
    pairs=[]
    for pair,rows in merged.items():
        ordered=sorted(rows.values(),key=lambda x:x['t'])[-MAX_SNAPSHOTS:]
        if ordered: pairs.append((pair,ordered))
    pairs.sort(key=lambda entry:entry[1][-1]['t'],reverse=True)
    return dict(pairs[:MAX_PAIRS])

def observe(state, pools, now):
    history=merge_observations(state.get('observations',{}),now=now)
    for pool in pools:
        try:
            created=pool['pairCreatedAt']
            if not finite(created) or not 0<=now-created/1000<=18000: continue
        except (KeyError,TypeError):
            continue
        row=snapshot(pool,now)
        if row is None: continue
        pair=pool['pairAddress']
        rows=history.setdefault(pair,[])
        # Keep enough spaced snapshots to compare separate five-minute windows.
        if rows and now-rows[-1]['t']<60: continue
        rows.append(row)
    state['observations']=merge_observations(history,now=now)

def assess(pool, history, now):
    current=snapshot(pool,now)
    if current is None: return 'missing_quality_metrics',None
    rows=history.get(pool['pairAddress'],[]) if isinstance(history,dict) else []
    if not isinstance(rows,list): rows=[]
    eligible=[r for r in rows if valid_record(r,now) and r['mint']==current['mint']
              and MIN_COMPARISON_SECONDS<=now-r['t']<=MAX_COMPARISON_SECONDS]
    if not eligible: return 'awaiting_comparison',None
    baseline=max(eligible,key=lambda r:r['t'])
    try:
        m5=pool['priceChange']['m5']; h1=pool['priceChange']['h1']
        cap=pool['marketCap']
        if not all(finite(v) for v in (m5,h1,cap)) or cap<=0:
            return 'missing_quality_metrics',None
        if m5>15 or h1>60: return 'late_price_surge',None
        if m5<0 or h1 < -15: return 'weak_price_momentum',None
        change=100*(current['price']/baseline['price']-1)
        if change>15: return 'price_ran_ahead',None
        if change < -5: return 'price_falling_since_comparison',None
        retention=current['lp']/baseline['lp']
        if retention<0.90: return 'liquidity_withdrawal',None
        if current['sells']<3: return 'insufficient_sell_activity',None
        if baseline['volume']<=0: return 'unverified_volume_acceleration',None
        acceleration=current['volume']/baseline['volume']
        if not all(finite(v) for v in (change,retention,acceleration)):
            return 'missing_quality_metrics',None
        if acceleration<1.1: return 'volume_not_growing',None
        if current['buys']<baseline['buys']: return 'buy_activity_fading',None
        share=current['buys']/max(current['buys']+current['sells'],1)
        depth=current['lp']/cap
        parts={
            'buy_pressure':round(25*min(max((share-0.5)/0.25,0),1),2),
            'volume_growth':round(25*min(acceleration/2,1),2),
            'liquidity_depth':round(20*min(depth/0.15,1),2),
            'buy_activity':round(15*min(current['buys']/30,1),2),
            'early_price':round(15*max(1-m5/30,0),2),
        }
        score=round(sum(parts.values()),1)
        detail={'score':score,'parts':parts,'volume_growth':acceleration,'buy_share':100*share,
                'liquidity_retention':100*retention,'price_change':change,
                'comparison_minutes':(now-baseline['t'])/60,'m5':m5,'h1':h1}
        return (None if score>=MIN_SCORE else 'quality_score_low'),detail
    except (KeyError,TypeError,ValueError,OverflowError,ZeroDivisionError):
        return 'missing_quality_metrics',None
