"""Rotating public multilingual retrieval; dynamic, source-bound entity discovery."""
import copy
import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from difflib import SequenceMatcher
import evidence
import narrative_v3
import market_data

REGIONS = [('US','en-US','en'),('CN','zh-CN','zh-Hans'),('JP','ja','ja'),('KR','ko','ko'),('ID','id','id'),('BR','pt-BR','pt-419')]
QUERIES = [
 ('games','game launch release trailer'),('ai','artificial intelligence new technology'),
 ('animals','viral animal meme'),('influencers','crypto influencer celebrity viral'),
 ('screen','movie anime donghua premiere'),('memes','internet meme viral video picture'),
 ('companies','company parody viral'),('breaking','breaking news'),
 ('exchange','crypto exchange listing announcement'),('community','meme coin community takeover'),
 ('global','热搜 病毒式 迷因 动漫 人工智能'),('global','話題 ミーム ゲーム アニメ'),
 ('global','화제 밈 게임 인공지능'),('open_world','trending viral')]
STOP = narrative_v3.STOP | set('gameplay demo legal friends out now delays brasil brazil china japan korea indonesia australia buatan lebih kecerdasan 人工智能 中国 日本 韩国 游戏 動画 ゲーム 話題 trending days videos photos pictures trendingnews launches headline headlines liveblog viralnews launch release trailer viral crypto coin token update report live watch announces announced launches price market stock shares best top reviews review unveils'.split())


def normalize(value):
    return re.sub(r'[^\w]+',' ',unicodedata.normalize('NFKC',str(value)).casefold(),flags=re.UNICODE).strip()


def contains(text, phrase):
    text=normalize(text); phrase=normalize(phrase)
    if not phrase: return False
    # CJK words have no space-separated boundaries.
    if re.search(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]',phrase): return phrase in text
    return bool(re.search(r'(?<!\w)'+re.escape(phrase)+r'(?!\w)',text))


def entities(articles, ai=None):
    labels={}
    for a in articles:
        title=a['title'].rsplit(' - ',1)[0]
        phrases=re.findall(r'\b[A-Z][\w-]{2,}(?:\s+[A-Z][\w-]{2,}){0,2}\b',title)
        phrases+=re.findall(r'[「『“\"]([^」』”\"]{2,40})[」』”\"]',title)
        # Whole script runs/quoted names only. Arbitrary CJK substrings are not entities.
        phrases+=re.findall(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]{2,20}',title)
        for phrase in phrases:
            key=normalize(phrase)
            if key and not any(w in STOP for w in key.split()): labels.setdefault(key,phrase)
    for phrase in (ai or {}).get('entities',[]):
        if isinstance(phrase,str) and 2<=len(phrase)<=60 and not any(w in STOP for w in normalize(phrase).split()): labels.setdefault(normalize(phrase),phrase)
    return list(labels.values())[:1500]


PLATFORM_HOSTS={'x.com','twitter.com','youtube.com','youtu.be','tiktok.com','facebook.com','instagram.com','reddit.com','csdn.net'}
MULTIPART_SUFFIXES={'com.cn','com.au','com.br','co.uk','co.jp','ne.jp','co.kr','co.id','ac.id','edu.cn','com.tw','com.hk'}


def publisher_family(host):
    """Conservative source grouping; does not assert ultimate corporate independence."""
    host=str(host).lower().rstrip('.').removeprefix('www.')
    parts=host.split('.')
    count=3 if '.'.join(parts[-2:]) in MULTIPART_SUFFIXES else 2
    return '.'.join(parts[-count:])


def headline(article):
    return article['title'].rsplit(' - ',1)[0]


def credible_article(article):
    family=publisher_family(article.get('publisher_host',''))
    text=normalize(headline(article))
    # A social/blog platform is not an independently verified newsroom.
    if family in PLATFORM_HOSTS:return False
    # Obvious repost/download spam cannot supply corroborating narrative evidence.
    return not any(marker in text for marker in ('full video','フルビデオ','twitter 動画 保存','動画 保存 ランキング'))


def trends(articles, ai, now, previous=None):
    articles=[a for a in articles if 0<=now-a['published_at']<=172800 and a.get('observed_at',now)<=now and credible_article(a)]
    found=[]
    for label in entities(articles,ai):
        hits=list({a['url']:a for a in articles if contains(headline(a),label)}.values())
        hosts={publisher_family(a['publisher_host']) for a in hits}; titles={normalize(a['title'].rsplit(' - ',1)[0]) for a in hits}
        if len(hosts)<2 or len(titles)<2: continue
        fresh=sum(now-a['published_at']<=21600 for a in hits)
        categories=sorted(set(a['category'] for a in hits))
        # A previously unseen repeated entity is an emergent category, no token seed needed.
        found.append({'label':label,'aliases':[label], 'category':categories,
            'dynamic_category':'emergent:'+normalize(label),
            'score':min(100,35+10*min(len(hosts),3)+3*min(len(titles),5)+5*min(fresh,4)),
            'publisher_count':len(hosts),'article_count':len(titles),'virality_score':None,
            'sources':sorted(hits,key=lambda a:-a['published_at'])[:4],
            'attention_basis':'distinct publisher domain families; corporate independence unverified; social virality unmeasured'})
    return sorted(found,key=lambda x:(-x['score'],-len(normalize(x['label']))))[:60]


def collect(api, state, now):
    old=state.get('global_feed_v5',{})
    if 0<=now-old.get('at',0)<600:
        value=copy.deepcopy(old['value']); value['trends']=trends(value['articles'],value.get('ai',{}),now); return value
    offset=int(now//600)%len(QUERIES)
    jobs=[]
    # Always cover six locales; rotate broad categories and an unbounded-news query.
    for i,region in enumerate(REGIONS): jobs.append((region,*QUERIES[(offset+i)%len(QUERIES)]))
    jobs.append((REGIONS[0],'open_world','trending viral news'))
    def read(job):
        (gl,hl,lang),category,query=job
        native={'CN':'热搜 OR 游戏 OR 动漫 OR 人工智能','JP':'話題 OR ゲーム OR アニメ','KR':'화제 OR 게임 OR 인공지능','ID':'viral OR gim OR kecerdasan buatan','BR':'viral OR jogos OR inteligência artificial'}
        localized='('+query+') OR ('+native[gl]+')' if gl in native else query
        url='https://news.google.com/rss/search?'+urlencode({'q':localized+' when:2d','gl':gl,'hl':hl,'ceid':gl+':'+lang})
        key=gl+':'+category
        try:
            rows=narrative_v3.parse_feed(evidence.public_read(url,api,as_text=True),category,now,normalizer=normalize)
            for a in rows: a.update(observed_at=now,region=gl)
            return key,rows,'ok' if rows else 'no_recent_articles'
        except Exception: return key,[],'unavailable'
    articles=[]; status={}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for key,rows,s in executor.map(read,jobs): articles+=rows; status[key]=s
    # Keep still-fresh prior rotation; never renew published_at or first observed_at.
    prior=old.get('value',{}).get('articles',[])
    dedup={a['url']:a for a in prior if 0<=now-a['published_at']<=172800}
    for a in articles:
        if a['url'] not in dedup: dedup[a['url']]=a
    articles=sorted(dedup.values(),key=lambda a:-a['published_at'])[:600]
    ai_old=state.get('global_ai_v5',{}); ai=ai_old.get('value',{})
    oidc=bool(os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN') and os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL'))
    if not 0<=now-ai_old.get('at',0)<10800:
        ai={'status':'not_configured','entities':[],'model_used':None}
        if oidc and articles:
            try:
                # Round robin locales so English does not monopolize 30-headline budget.
                selected=[]
                for region,_,_ in REGIONS: selected.extend([a for a in articles if a.get('region')==region][:5])
                remote=narrative_v3.worker_ai([{'title':a['title'][:160]} for a in selected[:30]],20)
                names=[x for x in remote.get('entities',[]) if isinstance(x,str) and len({publisher_family(a['publisher_host']) for a in articles if credible_article(a) and contains(headline(a),x)})>=2]
                ai={**remote,'entities':names}
            except Exception: ai={'status':'provider_unavailable','entities':[],'model_used':None}
        state['global_ai_v5']={'at':now,'value':ai}
    value={'articles':articles,'sources':status,'ai':ai,'trends':trends(articles,ai,now),
           'engine':'multilingual_evidence_rules_v5', 'llm_used':ai.get('status')=='ok',
           'coverage':'sampled public news, 6 rotating locales; not complete social/global coverage'}
    state['global_feed_v5']={'at':now,'value':value}
    return value


def match(pool, feed, now):
    token=pool.get('baseToken') or {}; name=token.get('name',''); symbol=token.get('symbol','')
    for trend in feed.get('trends',[]):
        label=trend['label']; exact=contains(name,label) or normalize(symbol)==normalize(label)
        left=normalize(name).replace(' ',''); right=normalize(label).replace(' ','')
        parody=(len(right)>=7 and abs(len(left)-len(right))<=3 and SequenceMatcher(None,left,right).ratio()>=.8)
        if exact or parody:
            # Name similarity is a hypothesis, never proof of official affiliation or image relationship.
            return dict(trend,reject=None if trend['score']>=70 else 'narrative_score_low',
                        relationship='name_match' if exact else 'possible_name_parody',
                        reason=('Nama cocok' if exact else 'Kemiripan nama; dugaan parodi')+' dengan '+label+'; afiliasi tidak terbukti.')
    return {'reject':'narrative_unverified','score':0,'sources':[],'virality_score':None}


def search_pools(api, feed, now, limit=12):
    topics=feed.get('trends',[])
    if not topics: return []
    start=int(now//300)%len(topics)
    queries=[]
    for t in (topics[start:]+topics[:start]):
        label=t['label']; queries.append(label)
        # Broad dynamic prefix retrieval discovers spelling parodies; matching still requires evidence.
        if len(label)>=7 and re.fullmatch(r'[A-Za-z0-9]+',label): queries.append(label[:-2])
        if len(queries)>=limit: break
    queries=queries[:limit]
    def read(query):
        try:
            result=api.request(api.DEX+'/latest/dex/search?'+urlencode({'q':query}))
            return [p for p in result.get('pairs',[]) if isinstance(p,dict) and p.get('chainId')=='solana'][:30]
        except Exception: return []
    pools=[]
    with ThreadPoolExecutor(max_workers=4) as executor:
        for rows in executor.map(read,queries): pools+=rows
    return market_data.merge_pools(pools)
