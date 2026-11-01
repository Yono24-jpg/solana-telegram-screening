"""Independent offline audit of the immutable 406-check evidence scope."""
import collections
import json
import math
from pathlib import Path


def valid(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0


def audit(evidence):
    source=evidence['extended_runtime']
    runs=[source['live_observation'],source['live_after_restart']]
    counts={};sets=collections.defaultdict(lambda:collections.defaultdict(set))
    details=[];mismatches=[];decisions=collections.Counter();decision_mints=collections.defaultdict(set)
    receipt_delays=[];receipt_unknown=0
    def note(category,status,mint):
        counts.setdefault(category,collections.Counter())[status]+=1
        sets[category][status].add(mint)
    for run_index,run in enumerate(runs):
        for row in run['rounds']:
            for index,candidate in enumerate(row['candidates']):
                e=candidate['event'];mint=e['mint'];observed_fail=[];unavailable=[]
                categories={}
                for field,category,minimum in [('liquidity_usd','liquidity',10000),
                    ('volume_5m_usd','volume_5m',1500),('buys_5m','buys_5m',12)]:
                    value=e.get(field)
                    status='unavailable' if not valid(value) else 'fail' if value<minimum else 'pass'
                    note(category,status,mint);categories[category]=status
                    if status=='fail':observed_fail.append(category)
                    if status=='unavailable':unavailable.append(category)
                age=e.get('pool_age_minutes')
                status='unavailable' if not valid(age) else 'fail' if age>60 else 'pass_lower_bound_only'
                note('pool_age',status,mint);categories['pool_age']=status
                if status=='fail':observed_fail.append('pool_age')
                b,s=e.get('buys_5m'),e.get('sells_5m')
                if not all(valid(v) and int(v)==v for v in (b,s)) or (b==0 and s==0):status='undefined_or_unavailable'
                elif s==0:status='pass_positive_buys_no_sells'
                else:status='fail' if b/s<1.5 else 'pass'
                note('buy_sell_ratio',status,mint);categories['buy_sell_ratio']=status
                if status=='fail':observed_fail.append('buy_sell_ratio')
                proof=candidate.get('mint_creation_proof')
                if proof and e.get('age_source')=='mint_creation' and valid(e.get('age_minutes')):
                    status='pass' if 1<=e['age_minutes']<=60 else 'fail'
                elif 'mint_history_scan' in candidate or 'mint_creation_proof' in candidate:status='unavailable_after_attempt'
                else:status='not_checked'
                note('mint_age',status,mint);categories['mint_age']=status
                security=candidate.get('security')
                for name,key in [('mint_authority','mint_revoked'),('freeze_authority','freeze_revoked')]:
                    if security and security.get('authority_data_verified'):
                        status='pass' if security.get(key) is True else 'fail'
                    else:status='unavailable' if security else 'not_checked'
                    note(name,status,mint);categories[name]=status
                if security and security.get('reason')=='unsupported_token_2022_extensions':status='rejected_token_2022'
                elif security and security.get('verified'):status='pass_legacy'
                else:status='unavailable' if security else 'not_checked'
                note('token_program',status,mint);categories['token_program']=status
                group='observed_market_violation' if observed_fail else 'token_2022_policy_only' if status=='rejected_token_2022' else 'unavailable_data_only'
                decisions[group]+=1;decision_mints[group].add(mint)
                matches=[p for p in row['raw_pairs'] if p.get('pairAddress')==candidate['pair']
                    and p.get('baseToken',{}).get('address')==mint]
                raw_fields=lambda p:dict(liquidity_usd=(p.get('liquidity') or {}).get('usd'),
                    volume_5m_usd=(p.get('volume') or {}).get('m5'),
                    buys_5m=(p.get('txns') or {}).get('m5',{}).get('buys'),
                    sells_5m=(p.get('txns') or {}).get('m5',{}).get('sells'))
                consistent=[p for p in matches if all(e.get(k)==v for k,v in raw_fields(p).items())]
                if not consistent:mismatches.append(dict(run=run_index,round=row['round'],mint=mint,issue='raw_metric_mismatch_or_missing_pair'))
                elif valid(consistent[0].get('pairCreatedAt')):
                    expected=(e['now']-consistent[0]['pairCreatedAt']/1000)/60
                    if not valid(age) or abs(age-expected)>1e-6:
                        mismatches.append(dict(mint=mint,issue='pool_age_conversion_mismatch'))
                details.append(dict(run=run_index,round=row['round'],index=index,mint=mint,
                    symbol=candidate['symbol'],decision_group=group,observed_failures=observed_fail,
                    unavailable_fields=unavailable,checks=categories,original_reasons=candidate['outcome']['reasons']))
                received=[q['received_at'] for q in run['requests'] if q.get('path')
                    and q['path'].startswith('/tokens/v1/solana/')
                    and mint in q['path'].rsplit('/',1)[-1].split(',') and q.get('received_at',math.inf)<=e['now']]
                if received:receipt_delays.append(e['now']-max(received))
                else:receipt_unknown+=1
    requests=[q for run in runs for q in run['requests']]
    api_failures=[q for q in requests if q.get('status')!='ok']
    errors=[error for run in runs for error in run['errors']]
    source_errors=[s for run in runs for r in run['rounds'] for s in r.get('discovery',{}).get('sources',[]) if 'error' in s]
    return dict(scope='extended_runtime live_observation + live_after_restart only',
        checks=len(details),unique_mints=len({d['mint'] for d in details}),
        overlapping_counts={k:dict(v) for k,v in counts.items()},
        unique_mints_by_category={k:{status:len(mints) for status,mints in group.items()} for k,group in sets.items()},
        disjoint_decisions=dict(decisions),unique_mints_by_disjoint_decision={k:len(v) for k,v in decision_mints.items()},
        api=dict(attempts=len(requests),failed_attempts=len(api_failures),round_errors=errors,source_errors=source_errors,
            receipt_timestamps_matched=len(receipt_delays),receipt_timestamps_unknown=receipt_unknown,
            receipt_delay_over_30s=sum(d>30 for d in receipt_delays),
            maximum_receipt_delay_seconds=round(max(receipt_delays,default=0),6),
            upstream_tick_freshness='not_proven_by_receipt_time'),
        raw_extraction_mismatches=mismatches,
        proven_reporting_error=dict(original_liquidity_rejections=158,actual_below_threshold=counts['liquidity']['fail'],
            missing_value_mislabeled_as_low=counts['liquidity']['unavailable']),
        note='Category counts overlap; not_checked is not a failure. Undefined 0/0 is not a passing ratio.',details=details)


if __name__=='__main__':
    result=audit(json.loads(Path('sniper_market_evidence.json').read_text()))
    Path('sniper_rejection_audit.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    print(json.dumps({k:v for k,v in result.items() if k!='details'},indent=2))
