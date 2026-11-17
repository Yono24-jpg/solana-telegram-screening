"""Read-only live wallet audit. No Telegram delivery or production state writes."""
import json
import time
from pathlib import Path
import bot
import data_intelligence as di
import security_v3 as security
from screening_rules import address
from v5_live_audit import ReadOnlyAPI


def run():
    state=json.loads(Path('state.json').read_text());api=ReadOnlyAPI()
    api.REQUEST_DEADLINE=bot.REQUEST_DEADLINE=time.monotonic()+150
    client=di.Client(api,state);api.DATA_INTELLIGENCE=client
    result={'at':time.time(),'mode':'READ ONLY; no alerts, trades or production-state writes','tokens':[]}
    try:result['finalized_slot']=client.rpc('getSlot',[{'commitment':'finalized'}])
    except Exception:result['connection']='unavailable'
    for token in client.trending()[:2]:
        mint=token['id'];row={'mint':mint,'symbol':token.get('symbol'),'security_complete':False,'verified_alert':False}
        try:
            report=client.rugcheck(mint);creator=report.get('creator')
            row['developer']=creator if address(creator) else None
            row['reported_insider_members']=report.get('graphInsidersDetected')
            row['reported_insider_networks']=len(report.get('insiderNetworks') or [])
            row['insider_scope']='RugCheck provider report plus sampled on-chain direct funding; not a complete graph'
            try:row['developer_check']=security.developer_check(report,api,time.time())
            except Exception:row['developer_check']={'reject':'developer_rpc_evidence_incomplete'}
            supply=client.rpc('getTokenSupply',[mint,{'commitment':'finalized'}])['value']
            largest=client.rpc('getTokenLargestAccounts',[mint,{'commitment':'finalized'}])['value'][:4]
            row['large_holders']=[{'token_account':r['address'],'supply_pct':100*int(r['amount'])/int(supply['amount']),
                                  'scope':'large token account; owner may be a pool, exchange or wallet'} for r in largest]
            wallets=[];transactions=[]
            if address(creator):wallets.append(creator)
            for r in largest[:4]:
                a=client.rpc('getAccountInfo',[r['address'],{'encoding':'jsonParsed','commitment':'finalized'}])['value']
                owner=a['data']['parsed']['info']['owner']
                if address(owner) and owner not in wallets:wallets.append(owner)
            buyers=[]
            for wallet in wallets[:5]:
                try:
                    signatures=client.rpc('getSignaturesForAddress',[wallet,{'limit':3,'commitment':'finalized'}])
                    for s in signatures[:2]:
                        if s.get('err') is not None:continue
                        tx=client.rpc('getTransaction',[s['signature'],{'encoding':'jsonParsed','commitment':'finalized','maxSupportedTransactionVersion':1}])
                        keys=tx['transaction']['message']['accountKeys']
                        signed=any(isinstance(k,dict) and k.get('pubkey')==wallet and k.get('signer') is True for k in keys)
                        delta=security.owner_balances(tx['meta'].get('postTokenBalances'),wallet,mint)-security.owner_balances(tx['meta'].get('preTokenBalances'),wallet,mint)
                        transactions.append({'signature':s['signature'],'wallet':wallet,'slot':tx.get('slot'),'block_time':tx.get('blockTime'),
                            'finalized_rpc':True,'signer_verified':signed,'transaction_success':tx['meta'].get('err') is None,
                            'age_seconds':time.time()-tx['blockTime'] if isinstance(tx.get('blockTime'),(int,float)) else None,
                            'raw_token_delta':delta,'token_supply_delta_pct':100*delta/int(supply['amount']),
                            'scope':'observed token movement, not necessarily a swap or a current whale purchase'})
                        if signed and delta>0 and tx['meta'].get('err') is None:buyers.append({'kind':'buy','wallet':wallet})
                except Exception:transactions.append({'wallet':wallet,'status':'history_or_transaction_unavailable'})
            row['wallet_transactions']=transactions
            try:row['funding_check']=security.funding_check(report,{'transactions':buyers},api,time.time())
            except Exception:row['funding_check']={'reject':'funding_sample_incomplete','complete_graph':False}
        except Exception:row['status']='partial_rpc_or_provider_evidence'
        result['tokens'].append(row)
    result['provider_status']=client.status;result['usage']=client.usage()
    result['helius_api_used']=sum(client.rpc_metrics.get('helius',{}).values())>0
    Path('reports').mkdir(exist_ok=True)
    Path('reports/helius-wallet-audit.json').write_text(json.dumps(result,indent=2))
    print('HELIUS_WALLET_AUDIT '+json.dumps(result))
    if not result['helius_api_used']:raise SystemExit('HELIUS_CONNECTION_NOT_VERIFIED')
    return result


if __name__=='__main__':run()
