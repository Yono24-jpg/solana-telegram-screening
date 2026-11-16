"""Public live integration audit. No Telegram token or signing capability is supplied."""
import json
import time
from pathlib import Path
import bot
import scanner_v5

class ReadOnlyAPI:
    DEX=bot.DEX
    PROGRAM=bot.PROGRAM
    REQUEST_DEADLINE=None
    KEYBOARD=bot.KEYBOARD
    request=staticmethod(bot.request)
    security_reason=staticmethod(bot.security_reason)
    rugcheck_risk_reason=staticmethod(bot.rugcheck_risk_reason)
    def tg(self,*args,**kwargs): raise RuntimeError('telegram_disabled_read_only_audit')
    def save(self,state): pass

if __name__=='__main__':
    bot.REQUEST_DEADLINE=time.monotonic()+200
    api=ReadOnlyAPI();api.REQUEST_DEADLINE=bot.REQUEST_DEADLINE
    state=json.loads(Path('state.json').read_text()) if Path('state.json').exists() else {}
    state['enabled']=True
    report=scanner_v5.run(state,None,api,dry_run=True)
    assert report['sent']==0 and report['version']=='5.1'
    assert report['health_notification']['status']=='read_only'
    Path('reports/live-v5.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('LIVE_V5_AUDIT_OK '+json.dumps({'seen':report['seen'],'sent':report['sent'],'health':report['health'],
                                       'trends':len(report['narrative']['trends']),'rejected':report['rejected'],
                                       'evaluations':report['evaluations'],'evaluation_status':report['evaluation_status'],'evaluation_fetch':report.get('evaluation_fetch')}))
