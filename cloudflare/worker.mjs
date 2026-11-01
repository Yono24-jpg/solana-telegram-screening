// Always-on Cloudflare scanner. No Telegram controls, webhook, or update polling.
const DEX='https://api.dexscreener.com';
const DEXFUN='https://data.dex.fun';
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const key=x=>typeof x==='string'&&/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(x);
const esc=x=>String(x).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const valuation=p=>p?._source==='dexpaprika'?{usd:p.fdv,label:'FDV'}:{usd:p?.marketCap,label:'MCap'};
export function normalizePaprika(p,pair,now){
 if(!p||p.chain!=='solana'||p.id!==pair||!key(pair)||!key(p.base_token_id)||!key(p.quote_token_id)||p.base_token_id===p.quote_token_id)return null;
 const token=p.tokens?.find(t=>t.id===p.base_token_id),created=Date.parse(p.created_at)/1000,priced=Date.parse(p.price_time)/1000,updated=Date.parse(p.last_updated)/1000,m5=p['5m'],h1=p['1h'];
 if(!token||typeof token.symbol!=='string'||!token.symbol.trim()||!finite(token.fdv)||token.fdv<=0||!finite(created)||created>now||!finite(priced)||!finite(updated)||priced>now+5||updated>now+5||now-priced>120||now-updated>120)return null;
 if(!finite(p.last_price_usd)||p.last_price_usd<=0||!finite(p.liquidity_usd)||p.liquidity_usd<0||!finite(m5?.volume_usd)||m5.volume_usd<0||!Number.isInteger(m5.buys)||m5.buys<0||!Number.isInteger(m5.sells)||m5.sells<0||!finite(m5.last_price_usd_change)||!finite(h1?.last_price_usd_change))return null;
 return {chainId:'solana',pairAddress:pair,baseToken:{address:token.id,symbol:token.symbol},quoteToken:{address:p.quote_token_id},pairCreatedAt:created*1000,priceUsd:String(p.last_price_usd),fdv:token.fdv,liquidity:{usd:p.liquidity_usd},volume:{m5:m5.volume_usd},txns:{m5:{buys:m5.buys,sells:m5.sells}},priceChange:{m5:m5.last_price_usd_change,h1:h1.last_price_usd_change},_source:'dexpaprika',_sourceAt:Math.min(priced,updated)};
}
// Seeds discovery only. Final pool age and market/security checks remain tied to the existing pool-specific sources.
export function normalizeDexFunLaunches(envelope,stage,nowMs,limit=30){
 if(!envelope||envelope.stale!==false||!finite(envelope.asOf)||envelope.asOf>nowMs+5000||nowMs-envelope.asOf>90000||!Array.isArray(envelope.data)||!['new','bonding','graduated'].includes(stage))return [];
 const timeField=stage==='graduated'?'graduatedAt':'createdAt',seen=new Set(),out=[];
 for(const launch of envelope.data){
  const at=launch?.[timeField];
  if(launch?.stage!==stage||!key(launch?.mint)||!finite(at)||at<=0||at>nowMs||nowMs-at>600000||seen.has(launch.mint))continue;
  seen.add(launch.mint);out.push(launch.mint);if(out.length>=limit)break;
 }
 return out;
}
export function marketReason(p,now){
 if(p?.chainId!=='solana'||!key(p.pairAddress)||!key(p.baseToken?.address)||typeof p.baseToken.symbol!=='string'||!p.baseToken.symbol.trim())return 'identity_missing';
 const age=now-p.pairCreatedAt/1000,l=p.liquidity?.usd,v=p.volume?.m5,b=p.txns?.m5?.buys,s=p.txns?.m5?.sells,cap=valuation(p).usd;
 if(!finite(p.pairCreatedAt))return 'age_missing';
 if(age<300)return 'pool_under_5m';if(age>600)return 'pool_over_10m';
 if(!finite(l)||!finite(v)||!Number.isInteger(b)||!Number.isInteger(s)||!finite(cap)||cap<=0)return 'market_data_missing';
 if(l<10000)return 'low_liquidity';if(v<1500)return 'low_volume';if(b<12||s<3)return 'insufficient_trades';
 if(b/s<1.5)return 'weak_buy_pressure';if(l/cap<.08)return 'shallow_liquidity';return null;
}
export function market(p,now){return marketReason(p,now)===null;}
function snap(p,t){const price=typeof p.priceUsd==='string'?Number(p.priceUsd):p.priceUsd;return finite(price)&&price>0?{t,mint:p.baseToken.address,price,lp:p.liquidity.usd,volume:p.volume.m5,buys:p.txns.m5.buys,sells:p.txns.m5.sells,created:p.pairCreatedAt/1000,symbol:p.baseToken.symbol,source:p._source||'dexscreener',providerAt:p._sourceAt||t}:null;}
export function assess(p,rows,now){
 const reason=marketReason(p,now);if(reason)return {reason};
 const cur=snap(p,now),m5=p.priceChange?.m5,h1=p.priceChange?.h1;
 if(!cur||!finite(m5)||!finite(h1))return {reason:'momentum_data_missing'};
 if(m5<0||h1< -15)return {reason:'falling_momentum'};
 if(m5>80)return {reason:'overextended_5m'};
 const base=(rows||[]).filter(r=>r.mint===cur.mint&&(r.source||'dexscreener')===cur.source&&finite(r.t)&&now-r.t>=120&&now-r.t<=480&&finite(r.price)&&r.price>0&&finite(r.lp)&&r.lp>0&&finite(r.volume)&&r.volume>0&&Number.isInteger(r.buys)&&r.buys>=0).sort((a,b)=>b.t-a.t)[0];
 if(!base)return {reason:'awaiting_2m_comparison'};
 if(cur.source==='dexpaprika'&&cur.providerAt-(base.providerAt||base.t)<120)return {reason:'provider_snapshot_not_progressing'};
 const change=100*(cur.price/base.price-1),retention=cur.lp/base.lp,growth=cur.volume/base.volume;
 if(change>40)return {reason:'price_ran_ahead_of_baseline'};if(change<0)return {reason:'price_falling_since_baseline'};
 if(retention<.9)return {reason:'liquidity_withdrawal'};
 const share=cur.buys/(cur.buys+p.txns.m5.sells);
 const continuation=growth>=.9&&cur.volume>=10000&&cur.buys>=50&&share>=.62&&cur.lp>=15000;
 if(growth<1.1&&!continuation)return {reason:'volume_not_building'};
 if(cur.buys<base.buys*.9)return {reason:'buy_activity_fading'};
 const clamp=x=>Math.max(0,Math.min(x,1));
 const parts=[25*clamp((share-.5)/.25),25*Math.min(growth/1.5,1),20*Math.min(cur.lp/valuation(p).usd/.15,1),15*Math.min(cur.buys/30,1),15*Math.max(1-change/80,0)];
 const score=Math.round(parts.reduce((a,b)=>a+Math.round(b*100)/100,0)*10)/10;
 if(score<70)return {reason:'score_below_70',score};
 return {reason:null,score,growth,retention,change,minutes:(now-base.t)/60,level:score>=85?'Momentum kuat':'Momentum berkembang',signal:growth>=1.1?'volume_bertumbuh':'aktivitas_kuat_bertahan'};
}
export function quality(p,rows,now){const q=assess(p,rows,now);return q.reason===null?q:null;}
export function observePerformance(entry,p,now){
 const price=typeof p?.priceUsd==='string'?Number(p.priceUsd):p?.priceUsd;
 if(!p||p.chainId!=='solana'||p.pairAddress!==entry.pair||p.baseToken?.address!==entry.mint||!finite(price)||price<=0||!finite(p.liquidity?.usd)||p.liquidity.usd<0||!finite(entry.alertPrice)||entry.alertPrice<=0)return null;
 const high=Math.max(entry.high||entry.alertPrice,price),low=Math.min(entry.low||entry.alertPrice,price);
 return {...entry,lastPrice:price,lastAt:now,lastSource:p._source||'dexscreener',high,low,liquidity:p.liquidity.usd,gain:100*(price/entry.alertPrice-1),peakGain:100*(high/entry.alertPrice-1),worstGain:100*(low/entry.alertPrice-1)};
}
export function performanceText(e){return `\n\nPEMANTAUAN SETELAH ALERT (bukan sinyal baru)\nHarga alert $${e.alertPrice.toPrecision(6)} → terpantau $${e.lastPrice.toPrecision(6)}\nPerubahan ${e.gain.toFixed(1)}% · tertinggi teramati ${e.peakGain.toFixed(1)}% · terendah teramati ${e.worstGain.toFixed(1)}%\nLP terpantau $${Math.round(e.liquidity)}; keamanan saat ini belum diperiksa ulang.\nDiperbarui ${new Date((e.lastAt+32400)*1000).toISOString().slice(0,19).replace('T',' ')} WIT\nAngka berbasis sampel harga, belum memperhitungkan biaya/slippage; bukan profit transaksi.`;}
export function mintSafe(a){
 if(!a||a.executable!==false||!['TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA','TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'].includes(a.owner)||a.data?.[1]!=='base64')return false;
 try{
  const bytes=Uint8Array.from(atob(a.data[0]),c=>c.charCodeAt(0)),v=new DataView(bytes.buffer);
  if(bytes.length<82||bytes[45]!==1||v.getUint32(0,true)!==0||v.getUint32(46,true)!==0)return false;
  if(bytes.length===82)return true;
  if(a.owner!=='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'||bytes.length<166||bytes[165]!==1||bytes.slice(82,165).some(x=>x!==0))return false;
  let i=166;const seen=new Set();while(i<bytes.length){if(bytes.slice(i).every(x=>x===0))return true;if(i+4>bytes.length)return false;const kind=v.getUint16(i,true),size=v.getUint16(i+2,true);i+=4;if(i+size>bytes.length||seen.has(kind)||!(kind===18&&size===64||kind===19&&size>=64))return false;seen.add(kind);i+=size;}return true;
 }catch{return false;}
}
async function context(env){
 let count=0,rates={},discoveryProof=null,knownFreeKey=false;const upstreamErrors=[];
 const keyFingerprint=typeof env.DEXPAPRIKA_API_KEY==='string'?Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(env.DEXPAPRIKA_API_KEY))),b=>b.toString(16).padStart(2,'0')).join(''):null;
 const dexFunKey=typeof env.DEXFUN_API_KEY==='string'?env.DEXFUN_API_KEY.trim():'';
 const dexFunKeyFingerprint=dexFunKey?Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(dexFunKey))),b=>b.toString(16).padStart(2,'0')).join(''):null;
 const seenHosts=new Set();
 async function json(url,init={}){
  const host=new URL(url).hostname,now=Date.now()/1000,cache=globalThis.caches?.default,cacheKey=new Request('https://solana-screening-minute.maille47604.workers.dev/_provider_cooldown/'+host);
  if(!seenHosts.has(host)){seenHosts.add(host);if(cache)try{const saved=await cache.match(cacheKey);if(saved){const j=await saved.json();if(finite(j.until))rates[host]=Math.max(rates[host]||0,j.until);}}catch{}}
  if((rates[host]||0)>now)throw Error('provider_rate_limited');
  if(++count>34)throw Error('request_budget');
  const auth=host==='api.dexpaprika.com'&&env.DEXPAPRIKA_API_KEY?{Authorization:env.DEXPAPRIKA_API_KEY}:host==='data.dex.fun'&&dexFunKey?{Authorization:'Bearer '+dexFunKey}:{};
  const r=await fetch(url,{...init,headers:{'User-Agent':'Mozilla/5.0 (compatible; SolanaScreening/1.0)',...auth,...(init.headers||{})},signal:AbortSignal.timeout(10000)});
  if(!r.ok){
   upstreamErrors.push({host,status:r.status});
   if(r.status===429){
    const h=r.headers.get('Retry-After'),seconds=h!==null&&Number.isFinite(Number(h))?Number(h):(Date.parse(h||'')-Date.now())/1000;
    const wait=Math.max(60,Math.min(finite(seconds)&&seconds>0?seconds:60,86400));rates[host]=Math.ceil(now+wait);
    if(cache)try{await cache.put(cacheKey,new Response(JSON.stringify({until:rates[host]}),{headers:{'Content-Type':'application/json','Cache-Control':'public,max-age='+Math.ceil(wait)}}));}catch{}
   }
   throw Error('http_'+r.status);
  }
  if(host==='api.dexpaprika.com'){
   const rawPlan=r.headers.get('x-api-plan'),plan=rawPlan?.trim().toLowerCase()||'missing';
   discoveryProof={plan:['free','keyless','dev','pro','enterprise','missing'].includes(plan)?plan:'other',headerPresent:rawPlan!==null,finalHost:r.url?new URL(r.url).hostname:host,redirected:!!r.redirected,keyType:typeof env.DEXPAPRIKA_API_KEY,keyLength:typeof env.DEXPAPRIKA_API_KEY==='string'?env.DEXPAPRIKA_API_KEY.length:0};
   if(auth.Authorization&&plan!=='free'&&!(plan==='missing'&&knownFreeKey))throw Error('discovery_key_not_verified_free');
   if(auth.Authorization&&plan==='free')knownFreeKey=true;
  }
  if(host==='data.dex.fun'&&r.url&&new URL(r.url).hostname!==host)throw Error('dexfun_redirect_rejected');
  delete rates[host];return r.json();
 }
 async function rpc(method,params){const j=await json(env.SOLANA_RPC_URL||'https://api.mainnet-beta.solana.com',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});if(j.error||j.result===undefined)throw Error('rpc_rejected');return j.result;}
 async function tg(method,data){const j=await json('https://api.telegram.org/bot'+env.TELEGRAM_BOT_TOKEN+'/'+method,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!j.ok)throw Error('telegram_rejected');return j.result;}
 return {json,rpc,tg,count:()=>count,errors:()=>upstreamErrors,useRates:r=>{rates=r;},discoveryAuthenticated:!!env.DEXPAPRIKA_API_KEY,discoveryProof:()=>discoveryProof,keyFingerprint:()=>keyFingerprint,trustPreviouslyVerifiedFreeKey:()=>{knownFreeKey=true;},verifiedFreeKeyFingerprint:()=>knownFreeKey?keyFingerprint:null,dexFunAuthenticated:!!dexFunKey,dexFunKeyFingerprint:()=>dexFunKeyFingerprint};
}
async function dexFunSeeds(c,state,now){
 const cache=state.dexfun||{at:0,newMints:[],bondingMints:[],graduatedMints:[],blockedUntil:0};
 const fp=c.dexFunKeyFingerprint();
 if(cache.keyFingerprint&&cache.keyFingerprint!==fp){cache.at=0;cache.blockedUntil=0;cache.newMints=[];cache.bondingMints=[];cache.graduatedMints=[];cache.error=null;}
 cache.keyFingerprint=fp;
 if(!c.dexFunAuthenticated){cache.newMints=[];cache.bondingMints=[];cache.graduatedMints=[];cache.error='key_not_configured';state.dexfun=cache;return [];}
 if(now>=cache.blockedUntil&&now-cache.at>=50){
  cache.at=now;cache.newMints=[];cache.bondingMints=[];cache.graduatedMints=[];cache.error=null;cache.asOf=null;
  for(const stage of ['new','bonding','graduated'])try{
   const j=await c.json(DEXFUN+'/v1/launches?stage='+stage+'&sort=newest&limit=200');
   const mints=normalizeDexFunLaunches(j,stage,Date.now(),20);
   if(stage==='new')cache.newMints=mints;else if(stage==='bonding')cache.bondingMints=mints;else cache.graduatedMints=mints;
   cache.asOf=Math.max(cache.asOf||0,finite(j.asOf)?j.asOf:0);
  }catch(e){cache.error=e.message;}
  if(!cache.newMints.length&&!cache.bondingMints.length&&!cache.graduatedMints.length&&!cache.error)cache.error='no_fresh_launches';
  if(cache.error==='http_401')cache.blockedUntil=now+3600;
  if(cache.error==='http_403')cache.blockedUntil=now+86400;
 }
 const fresh=now-cache.at<=90&&cache.asOf!==null&&cache.asOf<=Date.now()+5000&&Date.now()-cache.asOf<=90000;
 state.dexfun=cache;
 return fresh?[...new Set([...cache.graduatedMints,...cache.bondingMints,...cache.newMints])].slice(0,60):[];
}
async function discover(c,state={},now=Math.floor(Date.now()/1000)){
 const pools=new Map(),mints=new Set();
 // Keyless: <=7,200/30d; registered free key: <=43,200/30d. Never use a paid host.
 // Keep only pool addresses; never substitute this source's metrics for DEX validation.
 const cache=state.discovery||{at:0,pools:[]},authenticated=c.discoveryAuthenticated;
 if(cache.verifiedFreeKeyFingerprint&&cache.verifiedFreeKeyFingerprint===c.keyFingerprint())c.trustPreviouslyVerifiedFreeKey();
 else if(cache.verifiedFreeKeyFingerprint&&cache.verifiedFreeKeyFingerprint!==c.keyFingerprint())delete cache.verifiedFreeKeyFingerprint;
 if(cache.validationRevision!=='free_plan_retry_v2'){
  if(cache.error==='discovery_key_not_verified_free'){cache.blockedUntil=0;cache.at=0;delete cache.error;}
  cache.validationRevision='free_plan_retry_v2';
 }
 if(cache.authenticated!==authenticated){cache.blockedUntil=0;cache.at=0;cache.authenticated=authenticated;}
 if((authenticated||Math.floor(now/60)%6===0)&&now-cache.at>=(authenticated?50:300)&&now>=(cache.blockedUntil||0)){
  cache.at=now;
  try{const j=await c.json('https://api.dexpaprika.com/networks/solana/pools/search?order_by=created_at&sort=desc&limit=50&created_after=-10m&liquidity_usd_min=5000');delete cache.error;cache.pools=(j.results||[]).filter(p=>p.chain==='solana'&&key(p.id)&&finite(Date.parse(p.created_at))&&now-Date.parse(p.created_at)/1000>=0&&now-Date.parse(p.created_at)/1000<=600).map(p=>({id:p.id,created:Date.parse(p.created_at)/1000,lp:finite(p.liquidity_usd)?p.liquidity_usd:null,volume:finite(p.volume_usd_24h)?p.volume_usd_24h:null,change5m:finite(p.price_change_percentage_5m)?p.price_change_percentage_5m:null}));}
  catch(e){cache.error=e.message;if(e.message==='http_402')cache.blockedUntil=now+2592000;else if(e.message==='http_403')cache.blockedUntil=now+86400;else if(e.message==='discovery_key_not_verified_free')cache.blockedUntil=now+180;}
  cache.proof=c.discoveryProof();cache.verifiedFreeKeyFingerprint=c.verifiedFreeKeyFingerprint();
 }
 cache.pools=(cache.pools||[]).filter(p=>now-p.created>=0&&now-p.created<=600);state.discovery=cache;
 const dexFunMints=await dexFunSeeds(c,state,now);
 for(const mint of dexFunMints)if(mints.size<90)mints.add(mint);
 const pap=cache.pools.map(p=>p.id);
 for(let i=0;i<pap.length;i+=20)try{const j=await c.json(DEX+'/latest/dex/pairs/solana/'+pap.slice(i,i+20).join(','));for(const p of j.pairs||[])if(p.chainId==='solana'&&pap.includes(p.pairAddress))pools.set(p.pairAddress,p);}catch{}
 for(const path of ['/token-profiles/latest/v1','/community-takeovers/latest/v1','/token-boosts/latest/v1','/ads/latest/v1'])try{const a=await c.json(DEX+path);if(Array.isArray(a))for(const t of a)if(t.chainId==='solana'&&key(t.tokenAddress)&&mints.size<90)mints.add(t.tokenAddress);}catch{}
 const add=a=>{if(Array.isArray(a))for(const p of a)if(key(p?.pairAddress))pools.set(p.pairAddress,p);};
 const list=[...mints];for(let i=0;i<list.length;i+=30)try{add(await c.json(DEX+'/tokens/v1/solana/'+list.slice(i,i+30).join(',')));}catch{}
 for(let page=1;page<=2;page++)try{const g=await c.json('https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page='+page);const pairs=(g.data||[]).map(x=>x.attributes?.address).filter(key);for(let i=0;i<pairs.length;i+=20){const d=await c.json(DEX+'/latest/dex/pairs/solana/'+pairs.slice(i,i+20).join(','));add(d.pairs);}}catch(e){if(e.message==='http_429')break;}
 return pools;
}
async function refreshPairs(c,addresses,pools){
 const ids=[...new Set(addresses)].filter(key);for(let i=0;i<ids.length;i+=20){if(c.count()>18)break;try{const j=await c.json(DEX+'/latest/dex/pairs/solana/'+ids.slice(i,i+20).join(','));for(const p of j.pairs||[])if(p.chainId==='solana'&&ids.includes(p.pairAddress))pools.set(p.pairAddress,p);}catch{}}
}
async function paprikaPool(c,state,pair,now){
 if(!c.discoveryAuthenticated||(state.discovery?.blockedUntil||0)>now)return null;
 try{return normalizePaprika(await c.json('https://api.dexpaprika.com/networks/solana/pools/'+pair),pair,Math.floor(Date.now()/1000));}
 catch(e){if(e.message==='http_402'&&state.discovery){state.discovery.error='http_402';state.discovery.blockedUntil=now+2592000;}throw e;}
}
async function fallbackMarket(c,state,pools,status,now,rows){
 status.paprikaMarketReads=0;status.paprikaMarketValid=0;
 if(Math.floor(now/60)%3!==0||!c.discoveryAuthenticated||(state.discovery?.blockedUntil||0)>now)return;
 const eligible=(state.discovery?.pools||[]).filter(p=>now-p.created>=0&&now-p.created<=600&&finite(p.lp)&&p.lp>=10000&&finite(p.volume)&&p.volume>=1500&&finite(p.change5m)&&p.change5m>=0&&p.change5m<=80&&!pools.has(p.id));
 const rank=(a,b)=>Math.log1p(b.volume)*Math.log1p(b.lp)-Math.log1p(a.volume)*Math.log1p(a.lp);
 const ready=eligible.filter(p=>now-p.created>=300&&(rows[p.id]||[]).some(r=>r.source==='dexpaprika'&&now-r.t>=120&&now-r.t<=480)).sort(rank);
 const early=eligible.filter(p=>now-p.created<300).sort(rank),selected=[];
 if(ready.length)selected.push(ready[0]);if(early.length)selected.push(early[0]);
 for(const p of eligible.sort(rank))if(selected.length<2&&!selected.includes(p))selected.push(p);
 for(const p of selected){if(c.count()>22)break;status.paprikaMarketReads++;try{const n=await paprikaPool(c,state,p.id,now);if(n){pools.set(n.pairAddress,n);status.paprikaMarketValid++;}}catch{status.errors++;}}
}
async function track(c,env,state,status,now,pools){
 const entries=(state.alerts||[]).filter(e=>finite(e.alertAt)&&now-e.alertAt>=0&&now-e.alertAt<604800&&Number.isInteger(e.messageId)&&e.messageId>0).slice(-200);
 const active=entries.filter(e=>now-e.alertAt<=86400).slice(-40),market=new Map();
 await refreshPairs(c,active.map(e=>e.pair),market);let edits=0;
 if(Math.floor(now/60)%15===0&&c.discoveryAuthenticated){const missing=active.filter(e=>!market.has(e.pair)).sort((a,b)=>(a.lastAt||0)-(b.lastAt||0));if(missing.length)try{const p=await paprikaPool(c,state,missing[0].pair,now);if(p)market.set(p.pairAddress,p);}catch{status.errors++;}}
 state.alerts=entries.map(entry=>{
  if(!active.includes(entry))return {...entry,tracking:now-entry.alertAt>86400?'ended_24h':'capacity_paused'};
  const p=market.get(entry.pair);if(p)pools.set(entry.pair,p);
  const updated=observePerformance(entry,p,now);
  return updated?{...updated,tracking:'active'}:{...entry,tracking:'market_unavailable'};
 });
 for(const e of state.alerts){
  if(e.lastAt!==now||edits>=2||c.count()>=30)continue;
  const up=Math.floor(Math.max(e.peakGain,0)/50)*50,down=e.gain<=-20?Math.floor(-e.gain/20)*20:0;
  if(up<=(e.announcedUp||0)&&down<=(e.announcedDown||0))continue;
  edits++;e.updateStatus='unconfirmed';
  try{await c.tg('editMessageText',{chat_id:env.TELEGRAM_CHAT_ID,message_id:e.messageId,text:e.body+performanceText(e),parse_mode:'HTML',disable_web_page_preview:true});e.announcedUp=up;e.announcedDown=down;e.updateStatus='confirmed';status.performanceUpdates++;}catch{status.errors++;}
 }
 status.tracked=active.length;
}
async function run(env,scheduled=true){
 const now=Math.floor(Date.now()/1000),c=await context(env),day=new Date().toISOString().slice(0,10);
 const status={at:now,scheduled,mode:'always_on',engine:'momentum_v2.5',enabled:true,checked:0,passed:0,sent:0,errors:0,rejected:{},performanceUpdates:0};
 const reject=reason=>{status.rejected[reason]=(status.rejected[reason]||0)+1;};
 let state={observations:{},alerts:[]};
 try{
  state=await env.SCANNER_STATE.get('history','json')||state;
  state.cooldowns=state.cooldowns||{};c.useRates(state.cooldowns);
  const pools=new Map();await track(c,env,state,status,now,pools);
  const discovered=await discover(c,state,now);status.discovered=discovered.size;status.extraSourcePools=state.discovery?.pools?.length||0;status.extraSource={authenticated:!!state.discovery?.authenticated,error:state.discovery?.error||null,blockedUntil:state.discovery?.blockedUntil||null,proof:state.discovery?.proof||null};status.dexfun={configured:c.dexFunAuthenticated,newMints:state.dexfun?.newMints?.length||0,bondingMints:state.dexfun?.bondingMints?.length||0,graduatedMints:state.dexfun?.graduatedMints?.length||0,error:state.dexfun?.error||null};
  for(const [id,p]of discovered)pools.set(id,p);
  const rows=state.observations||{};await fallbackMarket(c,state,pools,status,now,rows);status.dexscreenerPools=discovered.size;status.discovered=pools.size;
  const watched=Object.entries(rows).filter(([,r])=>r.length&&now-r.at(-1).t<900).sort((a,b)=>b[1].at(-1).t-a[1].at(-1).t).map(([id])=>id).filter(id=>!pools.has(id)).slice(0,40);
  await refreshPairs(c,watched,pools);
  status.refreshedPools=pools.size;if(!pools.size){status.error='no_market_data';status.errors++;}
  const ranked=[],samples=[];status.newPools=0;
  for(const p of pools.values()){
   const q=assess(p,rows[p.pairAddress],now);if(q.reason)reject(q.reason);else ranked.push({p,q});
   const age=now-p.pairCreatedAt/1000;
   if(p?.chainId==='solana'&&key(p.pairAddress)&&key(p.baseToken?.address)&&finite(p.pairCreatedAt)&&age>=0&&age<=600&&finite(p.liquidity?.usd)&&p.liquidity.usd>0&&finite(p.volume?.m5)&&p.volume.m5>=0&&Number.isInteger(p.txns?.m5?.buys)&&p.txns.m5.buys>=0&&Number.isInteger(p.txns?.m5?.sells)&&p.txns.m5.sells>=0){
    status.newPools++;
    samples.push({pair:p.pairAddress,mint:p.baseToken.address,symbol:p.baseToken.symbol,at:now,poolAgeMinutes:Math.round(age/6)/10,liquidity:p.liquidity.usd,volume5m:p.volume.m5,buys:p.txns.m5.buys,sells:p.txns.m5.sells,price:snap(p,now)?.price||null,source:p._source||'dexscreener',valuation:valuation(p).usd||null,valuationType:valuation(p).label,score:q.score||null,reason:q.reason||'awaiting_security',security:'not_checked'});
    const s=snap(p,now);if(s){const r=(rows[p.pairAddress]||[]).filter(x=>now-x.t<=1800);if(!r.length||now-r.at(-1).t>=60)r.push(s);rows[p.pairAddress]=r.slice(-12);}
   }
  }
  status.qualityCandidates=ranked.length;
  ranked.sort((a,b)=>b.q.score-a.q.score);
  const unique=new Set(),candidates=ranked.filter(x=>{const mint=x.p.baseToken.address;if(unique.has(mint))return false;unique.add(mint);return true;}).slice(0,5),alerts=[];
  const daily=await env.SCANNER_STATE.get('deliveries:'+day,'json')||{count:0,mints:[]};
  let fallbackFinalChecks=0;
  let accounts=[];if(candidates.length&&c.count()<=27)try{accounts=(await c.rpc('getMultipleAccounts',[candidates.map(x=>x.p.baseToken.address),{encoding:'base64',commitment:'confirmed'}])).value||[];}catch{status.errors++;reject('rpc_mint_unavailable');}
  for(let i=0;i<candidates.length;i++){
   const {p}=candidates[i],mint=p.baseToken.address,sample=samples.find(x=>x.pair===p.pairAddress);
   if(daily.mints.includes(mint)){reject('already_alerted');continue;}
   if(c.count()>27){reject('complete_check_budget_exhausted');continue;}
   if(p._source==='dexpaprika'&&fallbackFinalChecks>=1){reject('authenticated_market_quota_budget');continue;}
   status.checked++;
   const fail=reason=>{reject(reason);if(sample){sample.reason=reason;sample.security='not_passed';}};
   try{
    if(!mintSafe(accounts[i])){fail('mint_security_not_verified');continue;}
    const supply=(await c.rpc('getTokenSupply',[mint,{commitment:'confirmed'}])).value?.amount;
    const holders=(await c.rpc('getTokenLargestAccounts',[mint,{commitment:'confirmed'}])).value;
    if(typeof supply!=='string'||!/^[0-9]+$/.test(supply)||BigInt(supply)<=0n||!Array.isArray(holders)||holders.length<10||!holders.slice(0,10).every(x=>typeof x.amount==='string'&&/^[0-9]+$/.test(x.amount))){fail('holder_data_incomplete');continue;}
    const top=holders.slice(0,10).reduce((a,x)=>a+BigInt(x.amount),0n);
    if(top*100n>BigInt(supply)*50n){fail('top10_accounts_over_50pct');continue;}
    const rug=await c.json('https://api.rugcheck.xyz/v1/tokens/'+mint+'/report/summary');
    if(!Array.isArray(rug.risks)||rug.risks.some(x=>typeof x.level!=='string'||['danger','critical'].includes(x.level.toLowerCase()))||!finite(rug.score_normalised)||rug.score_normalised<0||rug.score_normalised>=60){fail('rugcheck_not_passed');continue;}
    let latest;
    if(p._source==='dexpaprika'){fallbackFinalChecks++;latest=await paprikaPool(c,state,p.pairAddress,Math.floor(Date.now()/1000));}
    else{const fresh=await c.json(DEX+'/latest/dex/pairs/solana/'+p.pairAddress);latest=fresh.pairs?.find(x=>x.pairAddress===p.pairAddress&&x.baseToken?.address===mint);}
    const observedAt=Math.floor(Date.now()/1000),q=latest?.baseToken?.address===mint?quality(latest,rows[p.pairAddress],observedAt):null;
    if(!q){fail('fresh_momentum_not_passed');continue;}
    alerts.push({p:latest,q,top:Number(top*10000n/BigInt(supply))/100,observedAt});status.passed++;
    if(sample){sample.security='passed';sample.reason='ready';sample.score=q.score;}
   }catch{status.errors++;fail('security_request_failed');}
  }
  for(const {p,q,top,observedAt}of alerts.slice(0,5)){
   if(daily.count>=200||c.count()>=34)break;
   if(!market(p,Date.now()/1000)||Date.now()/1000-observedAt>30){reject('market_snapshot_expired_before_send');continue;}
   const mint=p.baseToken.address,price=snap(p,now)?.price;
   if(!finite(price)||price<=0){reject('alert_price_missing');continue;}
   daily.count++;daily.mints.push(mint);
   await env.SCANNER_STATE.put('deliveries:'+day,JSON.stringify(daily),{expirationTtl:172800});
   const text=`MOMENTUM SOLANA · ${esc(p.baseToken.symbol)}\n${q.level} · skor ${q.score}/100 (skor aturan, bukan probabilitas)\nHarga rujukan saat alert $${price.toPrecision(6)} · ${valuation(p).label} $${Math.round(valuation(p).usd)}\nSumber ${p._source||'dexscreener'}\nUmur pool ${Math.floor((Date.now()-p.pairCreatedAt)/60000)} menit (umur mint belum diverifikasi)\nLikuiditas $${Math.round(p.liquidity.usd)} · Volume 5m $${Math.round(p.volume.m5)}\nBUY/SELL 5m ${p.txns.m5.buys}/${p.txns.m5.sells}\nVolume ${q.growth.toFixed(2)}x pembanding ${q.minutes.toFixed(1)} menit · retensi LP ${(q.retention*100).toFixed(1)}%\nTop 10 akun token ${top}% (bukan wallet unik)\nMint/freeze authority nonaktif; RugCheck lolos pada waktu pemeriksaan.\nMint: <code>${mint}</code>\n<a href="https://axiom.trade/t/${mint}">Axiom</a> · <a href="https://dexscreener.com/solana/${p.pairAddress}">Chart</a>\nRisiko tetap tinggi; tidak menjamin kenaikan. Tanpa trading otomatis.`;
   const r=await c.tg('sendMessage',{chat_id:env.TELEGRAM_CHAT_ID,text,parse_mode:'HTML',disable_web_page_preview:true}),alertAt=Math.floor(Date.now()/1000);
   if(!Number.isInteger(r.message_id)||r.message_id<=0)throw Error('missing_delivery_receipt');
   status.sent++;state.alerts=state.alerts||[];
   state.alerts.push({mint,pair:p.pairAddress,symbol:p.baseToken.symbol,alertPrice:price,alertAt,observedAt,priceSource:p._source||'dexscreener',providerAt:p._sourceAt||observedAt,messageId:r.message_id,score:q.score,high:price,low:price,lastPrice:price,lastAt:alertAt,gain:0,peakGain:0,worstGain:0,announcedUp:0,announcedDown:0,tracking:'active',body:text});
   console.log(JSON.stringify({event:'telegram_alert_sent',message_id:r.message_id,mint,alertPrice:price,alertAt,score:q.score}));
  }
  state.observations=Object.fromEntries(Object.entries(rows).filter(([,r])=>r.some(x=>now-x.t<=1800)).sort((a,b)=>b[1].at(-1).t-a[1].at(-1).t).slice(0,160));
  state.alerts=(state.alerts||[]).slice(-200);
  state.samples=samples.sort((a,b)=>(b.score||0)-(a.score||0)||a.poolAgeMinutes-b.poolAgeMinutes).slice(0,10);
 }catch(e){status.errors++;status.error=/^[a-z_0-9]+$/.test(e.message)?e.message:'check_failed';}
 // 480 scheduled history writes + 200 reservations + <=200 extra receipt checkpoints/day.
 status.upstreamErrors=c.errors();status.requests=c.count();state.status=status;
 if(Math.floor(now/60)%3===0||status.sent>0)await env.SCANNER_STATE.put('history',JSON.stringify(state));
 console.log(JSON.stringify({event:'scanner_run',...status}));return status;
}
export default{
 async scheduled(event,env,ctx){ctx.waitUntil(run(env,true));},
 async fetch(request,env){
  const path=new URL(request.url).pathname;if(path==='/health')return Response.json({service:'solana-screening',engine:'momentum_v2.5',configured:!!env.SCANNER_STATE});
  if(path==='/data'){const s=await env.SCANNER_STATE.get('history','json')||{};return Response.json({status:s.status||{pending:true},samples:s.samples||[],results:(s.alerts||[]).map(({body,...entry})=>entry),note:'Samples are observations, not approved signals. Results exist only after a confirmed Telegram alert; price samples are not realised trading profit.'},{headers:{'Cache-Control':'no-store'}});}
  if(typeof env.DEPLOY_CHECK_KEY!=='string'||!env.DEPLOY_CHECK_KEY.trim()||request.headers.get('Authorization')!=='Bearer '+env.DEPLOY_CHECK_KEY)return new Response('Forbidden',{status:403});
  if(path==='/admin/probe'&&request.method==='POST'){
   const c=await context(env),s=await env.SCANNER_STATE.get('history','json')||{},now=Math.floor(Date.now()/1000),rejected={},qualified=[],diagnostic={errors:0};c.useRates(s.cooldowns||{});
   const pools=await discover(c,s,now);await fallbackMarket(c,s,pools,diagnostic,now,s.observations||{});
   for(const p of pools.values()){const q=assess(p,s.observations?.[p.pairAddress],now);if(q.reason)rejected[q.reason]=(rejected[q.reason]||0)+1;else qualified.push({symbol:p.baseToken.symbol,mint:p.baseToken.address,score:q.score,security:'not_checked'});}
   return Response.json({pools:pools.size,rejected,qualified,diagnostic,extraSource:{authenticated:!!s.discovery?.authenticated,pools:s.discovery?.pools?.length||0,error:s.discovery?.error||null,proof:s.discovery?.proof||null},dexfun:{configured:c.dexFunAuthenticated,newMints:s.dexfun?.newMints?.length||0,bondingMints:s.dexfun?.bondingMints?.length||0,graduatedMints:s.dexfun?.graduatedMints?.length||0,error:s.dexfun?.error||null},upstreamErrors:c.errors(),requests:c.count()});
  }
  if(path==='/admin/status')return Response.json((await env.SCANNER_STATE.get('history','json'))?.status||{pending:true});
  if(path==='/admin/test'&&request.method==='POST'){
   try{const c=await context(env),chat=await c.tg('getChat',{chat_id:env.TELEGRAM_CHAT_ID});if(!['channel','group','supergroup'].includes(chat.type))throw Error('unsupported_chat');const r=await c.tg('sendMessage',{chat_id:env.TELEGRAM_CHAT_ID,text:'UJI KONEKSI MOMENTUM V2 — scanner selalu aktif setiap 1 menit. Kandidat wajib lolos data pasar, pembanding momentum minimal 2 menit, mint/freeze, konsentrasi akun token, dan RugCheck. Harga alert serta perkembangan naik/turun akan dicatat setelah pengiriman kandidat berhasil. Pesan ini hanya uji koneksi; belum membuktikan adanya kandidat atau kenaikan harga.'});console.log(JSON.stringify({event:'telegram_test_sent',message_id:r.message_id,chat_type:chat.type}));return Response.json({ok:true,message_id:r.message_id,chat_type:chat.type,chat_title:chat.title});}catch{return Response.json({ok:false,error:'telegram_test_failed'},{status:502});}
  }
  return new Response('Not found',{status:404});
 }
};

