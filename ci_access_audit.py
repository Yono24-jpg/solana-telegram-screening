"""Read-only permission diagnosis. Never prints tokens or provider response bodies."""
import json
import os
from pathlib import Path
import urllib.request
import urllib.error

ACCOUNT='29ee31debc5b601f871467bf4547d875'


def run():
    token=os.environ.get('CLOUDFLARE_API_TOKEN','');account=os.environ.get('CLOUDFLARE_ACCOUNT_ID') or ACCOUNT
    result={'secret_present':bool(token),'account_matches_existing':account==ACCOUNT,'checks':{},'writes_attempted':False}
    checks={'verify_user':'/user/tokens/verify','list_accounts':'/accounts?per_page=1',
            'scheduler_settings':'/accounts/'+account+'/workers/scripts/mail-solana-scheduler/settings',
            'scheduler_cron':'/accounts/'+account+'/workers/scripts/mail-solana-scheduler/schedules',
            'kv_metadata':'/accounts/'+account+'/storage/kv/namespaces?per_page=1'}
    if token and account==ACCOUNT:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        for name,path in checks.items():
            try:
                req=urllib.request.Request('https://api.cloudflare.com/client/v4'+path,headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
                with urllib.request.build_opener(NoRedirect).open(req,timeout=10) as response:
                    raw=response.read(1000000);data=json.loads(raw)
                    result['checks'][name]={'http':response.status,'success':data.get('success') is True}
            except urllib.error.HTTPError as error:result['checks'][name]={'http':error.code,'success':False}
            except Exception:result['checks'][name]={'status':'transport_or_invalid_response','success':False}
    Path('reports').mkdir(exist_ok=True);Path('reports/ci-access-audit.json').write_text(json.dumps(result,indent=2))
    print('CI_ACCESS_AUDIT '+json.dumps(result))
    return result


if __name__=='__main__':run()
