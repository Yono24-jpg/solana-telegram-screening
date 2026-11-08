"""Read-only mainnet proof against PumpSwap's published example. No messages."""
import json
from pathlib import Path
import time
import bot
from evidence import rpc
from vault_checks import pool_vault, verify_vault


def main():
    bot.REQUEST_DEADLINE=time.monotonic()+35
    pool={'pairAddress':'GseMAnNDvntR5uFePZ51yZBXzNSn7GdFPkfHwfr6d77J',
          'baseToken':{'address':'7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump'}}
    result={'status':'unavailable','read_only':True,'pool':pool['pairAddress'],'stage':'fetch_pool_and_mint'}
    try:
        response=rpc(bot,'getMultipleAccounts',[[pool['pairAddress'],pool['baseToken']['address']],{'encoding':'base64','commitment':'finalized'}])
        pool_account,mint_account=response['value']
        result['stage']='decode_pool'
        proof=pool_vault(pool,pool_account)
        result['stage']='fetch_vault'
        vault=rpc(bot,'getAccountInfo',[proof['vault'],{'encoding':'base64','commitment':'finalized','minContextSlot':response['context']['slot']}])
        result['stage']='verify_vault'
        verify_vault(proof,vault['value'],mint_account['owner'])
        result.update(status='verified',protocol=proof['protocol'],vault=proof['vault'],slot=vault['context']['slot'])
    except Exception as exc:
        result['reason']='rpc_or_public_example_unavailable_or_unverified'
        result['error_type']=type(exc).__name__
    Path('reports').mkdir(exist_ok=True)
    Path('reports/vault-live-audit.json').write_text(json.dumps(result,indent=2))
    print('VAULT_LIVE_AUDIT '+json.dumps(result,sort_keys=True))
    return result


if __name__=='__main__':main()
