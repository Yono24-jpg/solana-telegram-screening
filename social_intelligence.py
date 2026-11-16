"""Public API samples, not a firehose. Never equate missing ads with organic reach."""
from urllib.parse import urlencode
import re
import evidence
from screening_rules import number


def sample(api, query, mint, now):
    out={'status':'unavailable','posts':[], 'unique_authors':None,'interactions':None,'contract_mentions':None,'score':None,
         'provider':'bluesky_public_appview','organic_status':'unknown','image_relationship':'unavailable'}
    try:
        raw=evidence.public_read('https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?'+urlencode({'q':query,'limit':25,'sort':'latest'}),api)
        if not isinstance(raw.get('posts'),list): return out
        rows=[]
        for p in raw['posts'][:25]:
            record=p.get('record') or {}; when=evidence.timestamp(record.get('createdAt')); author=p.get('author') or {}
            if when is None or not 0<=now-when<=3600 or not isinstance(author.get('did'),str): continue
            if not isinstance(record.get('text'),str) or not isinstance(p.get('uri'),str): continue
            metrics=[p.get(k) for k in ('likeCount','replyCount','repostCount')]
            rows.append({'uri':p['uri'],'author':author['did'],'at':when,'text':record['text'][:1000],
                         'interactions':sum(metrics) if all(number(x) and x>=0 for x in metrics) else None,
                         'avatar_url':author.get('avatar'), 'contract_mentioned':bool(re.search(r'(?<![1-9A-HJ-NP-Za-km-z])'+re.escape(mint)+r'(?![1-9A-HJ-NP-Za-km-z])',record['text']))})
        rows=list({r['uri']:r for r in rows}.values())
        out.update(status='observed',posts=rows,unique_authors=len({r['author'] for r in rows}),
                   contract_mentions=sum(r['contract_mentioned'] for r in rows),
                   interactions=sum(r['interactions'] for r in rows) if rows and all(r['interactions'] is not None for r in rows) else None)
    except Exception: pass
    return out


def observe(state, mint, social, public, pool, now):
    previous=state.setdefault('social_v5',{}).get(mint,{})
    # Compare only separately observed, same-provider samples, never cumulative totals to rates.
    posts=public.get('posts',[]); recent=[p for p in posts if now-p['at']<=300]
    current={'at':now,'unique_recent':len({p['author'] for p in recent}), 'recent_count':len(recent),
             'members':social.get('telegram',{}).get('members'), 'avatars':{p['author']:p.get('avatar_url') for p in posts if p.get('avatar_url')}}
    growth=None
    if public.get('status')=='observed' and previous.get('public_status')=='observed' and 300<=now-previous.get('at',0)<=900:
        baseline=previous.get('recent_count',0)
        growth=len(recent)/baseline if baseline>0 else None
    changes=[did for did,url in current['avatars'].items() if did in previous.get('avatars',{}) and previous['avatars'][did]!=url]
    before=previous.get('members'); members=current['members']
    community_growth=members-before if number(before) and number(members) and 300<=now-previous.get('at',0)<=3600 else None
    # URL changes are evidence of a URL change, not visual analysis of its contents.
    out={'public_status':public['status'],'mention_acceleration':growth,'avatar_url_changes':changes,
         'image_contents':'not_analyzed','members_change_observed':community_growth,
         'organic_status':'unknown', 'paid_boost_observed':bool((pool.get('boosts') or {}).get('active',0)),
         'virality_score':None, 'contract_mentions':public.get('contract_mentions')}
    if growth is not None and current['unique_recent']>=3 and public.get('interactions') is not None:
        out['virality_score']=round(min(100,20*min(3,growth)+5*min(8,current['unique_recent'])))
    current['public_status']=public['status']; state['social_v5'][mint]=current
    state['social_v5']=dict(sorted(state['social_v5'].items(),key=lambda x:-x[1]['at'])[:200])
    return out


def discover_contracts(api, feed, now):
    """Untrusted public CA mentions are discovery leads only, never evidence of safety."""
    from concurrent.futures import ThreadPoolExecutor
    from screening_rules import address
    from market_data import merge_pools
    topics=feed.get('trends',[])
    if not topics: return [],{'status':'no_verified_news_topics','contracts':0,'sources':{}}
    offset=int(now//300)%len(topics); chosen=(topics[offset:]+topics[:offset])[:3]
    def read(t):return t['label'],sample(api,t['label'],'1'*32,now)
    mints=set(); sources={}
    with ThreadPoolExecutor(max_workers=3) as executor:
        for label,value in executor.map(read,chosen):
            sources[label]=value['status']
            for row in value.get('posts',[]):
                for mint in re.findall(r'(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])',row['text']):
                    if address(mint):mints.add(mint)
    selected=sorted(mints)[:30]; pools=[]
    if selected:
        try:
            raw=api.request(api.DEX+'/tokens/v1/solana/'+','.join(selected))
            pools=[p for p in raw if isinstance(p,dict) and p.get('chainId')=='solana' and (p.get('baseToken') or {}).get('address') in selected] if isinstance(raw,list) else []
        except Exception: pass
    return merge_pools(pools),{'status':'sampled' if any(v=='observed' for v in sources.values()) else 'unavailable',
                               'sources':sources,'contracts':len(selected),'pools':len(pools),'trust':'unverified leads only'}
