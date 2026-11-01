"""Deploy the separate Worker using Actions secrets. Never log credentials."""
import json, os, secrets, time, urllib.request, urllib.error
from pathlib import Path

BASE='https://api.cloudflare.com/client/v4/'
TOKEN=os.environ.get('CLOUDFLARE_API_TOKEN','').strip()
NAME='solana-screening-minute'

def request(url, method='GET', data=None, headers=None, raw=False):
    req=urllib.request.Request(url,data=data,method=method,headers={'User-Agent':'Mozilla/5.0 (compatible; SolanaScannerDeployment/1.0)',**(headers or {})})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: body=r.read()
    except urllib.error.HTTPError as e:
        # Do not print the response: providers may echo credentials or request URLs.
        raise RuntimeError('http_'+str(e.code)) from None
    except Exception:
        raise RuntimeError('network_failed') from None
    return body if raw else json.loads(body)

def cf(path,method='GET',data=None,raw=False,ctype='application/json'):
    body=data if isinstance(data,bytes) else None if data is None else json.dumps(data).encode()
    j=request(BASE+path,method,body,{'Authorization':'Bearer '+TOKEN,'Content-Type':ctype},raw)
    if raw:return j
    if not j.get('success'):
        codes=[str(x.get('code','unknown')) for x in j.get('errors',[]) if isinstance(x,dict)]
        raise RuntimeError('cloudflare_rejected_codes_'+','.join(codes))
    return j.get('result')

def main():
    if not TOKEN:raise RuntimeError('missing_cloudflare_secret')
    if cf('user/tokens/verify').get('status')!='active':raise RuntimeError('token_inactive')
    accounts=cf('accounts?per_page=50')
    if len(accounts)!=1:raise RuntimeError('account_selection_required')
    account=accounts[0]['id'];prefix='accounts/'+account+'/'
    print('CLOUDFLARE_AUTH_OK',flush=True)
    namespaces=cf(prefix+'storage/kv/namespaces?per_page=100')
    namespace=next((x['id'] for x in namespaces if x['title']==NAME+'-state'),None)
    if not namespace:namespace=cf(prefix+'storage/kv/namespaces','POST',{'title':NAME+'-state'})['id']
    subdomain=cf(prefix+'workers/subdomain').get('subdomain')
    if not subdomain:raise RuntimeError('workers_subdomain_registration_required')
    bindings=[{'type':'kv_namespace','name':'SCANNER_STATE','namespace_id':namespace}]
    checkkey=secrets.token_urlsafe(36)
    for name,value in [('TELEGRAM_BOT_TOKEN',os.environ.get('TELEGRAM_BOT_TOKEN','')),('TELEGRAM_CHAT_ID',os.environ.get('TELEGRAM_CHAT_ID','')),('DEPLOY_CHECK_KEY',checkkey)]:
        if not value:raise RuntimeError('missing_'+name.lower())
        print('::add-mask::'+value,flush=True)
        bindings.append({'type':'secret_text','name':name,'text':value})
    if os.environ.get('SOLANA_RPC_URL'):
        bindings.append({'type':'secret_text','name':'SOLANA_RPC_URL','text':os.environ['SOLANA_RPC_URL']})
    metadata={'main_module':'worker.mjs','compatibility_date':'2026-10-01','bindings':bindings,'observability':{'enabled':True}}
    boundary='----'+secrets.token_hex(16)
    parts=[]
    for name,filename,ctype,body in [('metadata','metadata.json','application/json',json.dumps(metadata)),('worker.mjs','worker.mjs','application/javascript+module',Path('cloudflare/worker.mjs').read_text())]:
        parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"; filename="'+filename+'"\r\nContent-Type: '+ctype+'\r\n\r\n').encode()+body.encode()+b'\r\n')
    payload=b''.join(parts)+('--'+boundary+'--\r\n').encode()
    cf(prefix+'workers/scripts/'+NAME,'PUT',payload,ctype='multipart/form-data; boundary='+boundary)
    cf(prefix+'workers/scripts/'+NAME+'/subdomain','POST',{'enabled':True,'previews_enabled':False})
    cf(prefix+'workers/scripts/'+NAME+'/schedules','PUT',[{'cron':'* * * * *'}])
    schedule=cf(prefix+'workers/scripts/'+NAME+'/schedules')
    if not any(x.get('cron')=='* * * * *' for x in schedule.get('schedules',[])):raise RuntimeError('schedule_unverified')
    url='https://'+NAME+'.'+subdomain+'.workers.dev'
    print('WORKER_DEPLOYED '+url,flush=True)
    print('CRON_CONFIGURED every_1_minute',flush=True)
    for i in range(12):
        try:
            health=request(url+'/health')
            if health.get('configured'):
                # Wait for the new secret binding to propagate before sending anything.
                request(url+'/admin/status',headers={'Authorization':'Bearer '+checkkey})
                break
        except RuntimeError as e:
            print('WORKER_HEALTH_RETRY reason='+str(e),flush=True)
        time.sleep(5)
    else:raise RuntimeError('worker_health_failed')
    # Send exactly once. Never retry an uncertain Telegram delivery.
    test=request(url+'/admin/test','POST',b'{}',{'Authorization':'Bearer '+checkkey,'Content-Type':'application/json'})
    if test.get('ok') is not True or not isinstance(test.get('message_id'),int):raise RuntimeError('telegram_delivery_unverified')
    print('TELEGRAM_SEND_CONFIRMED '+json.dumps(test,ensure_ascii=False),flush=True)
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:
        f.write('Worker: '+url+'\n\nTelegram test: '+json.dumps(test,ensure_ascii=False)+'\n\n')
    # Confirm a real cron invocation via the state it writes, not a manual scan.
    probe=request(url+'/admin/probe','POST',b'{}',{'Authorization':'Bearer '+checkkey,'Content-Type':'application/json'})
    print('MARKET_SOURCE_PROBE '+json.dumps(probe),flush=True)
    start=int(time.time())
    for i in range(30):
        try:
            state=json.loads(cf(prefix+'storage/kv/namespaces/'+namespace+'/values/history',raw=True))
            status=state.get('status',{})
            if status.get('scheduled') is True and status.get('at',0)>=start-60:
                print('SCHEDULED_RUN_CONFIRMED '+json.dumps(status),flush=True)
                if status.get('enabled') and not status.get('discovered'):raise RuntimeError('scheduled_scan_has_no_market_data')
                with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write('Real scheduled run: '+json.dumps(status)+'\n')
                return
        except RuntimeError:pass
        print('WAITING_FOR_REAL_CRON attempt='+str(i+1),flush=True)
        time.sleep(20)
    raise RuntimeError('telegram_sent_but_cron_not_yet_observed')

if __name__=='__main__':
    try:main()
    except RuntimeError as e:
        print('DEPLOY_CHECK_FAILED '+str(e),flush=True)
        raise SystemExit(1)
