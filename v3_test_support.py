"""Synthetic fixtures used exclusively by offline tests; never live alerts."""
from test_upgrade import NOW


def narrative():
    return {'score':90,'reject':None,'reason':'Synthetic fixture','label':'GTA','sources':[
        {'url':'https://example.org/news','publisher':'Fixture','title':'GTA update','published_at':NOW-60}]}


def safety():
    return {'complete':True,'score':100,'reject':None,'risks':['Synthetic fixture'],
            'checks':{'provider':{'lp_locked_pct':100},'transactions':{'finalized_sells':3}}}


def approved(pool):
    pool['volume']['h1']=10000;pool['_security_v3']=safety();pool['_narrative_v3']=narrative()
    return pool


def feed():
    return {'engine':'evidence_rules_v3','llm_used':False,'articles':[], 'sources':{},'social_coverage':'fixture'}
