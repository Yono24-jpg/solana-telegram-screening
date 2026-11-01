// Always-on Cloudflare scanner. No Telegram controls, webhook, or update polling.
const DEX='https://api.dexscreener.com';
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const key=x=>typeof x==='string'&&/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(x);
const esc=x=>String(x).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
export function marketReason(p,now){
 if(p?.chainId!=='solana'||!key(p.pairAddress)||!key(p.baseToken?.address)||typeof p.baseToken.symbol!=='string')return 'identity_missing';
 const age=now-p.pairCreatedAt/1000,l=p.liquidity?.usd,v=p.volume?.m5,b=p.txns?.m5?.buys,s=p.txns?.m5?.sells;
 if(!finite(p.pairCreatedAt))return 'age_missing';
 if(age<300)return 'pool_under_5m';if(age>600)return 'pool_over_10m';
 if(!finite(l)||!finite(v)||!Number.isInteger(b)||!Number.isInteger(s)||!finite(p.marketCap)||p.marketCap<=0)return 'market_data_missing';
 if(l<10000)return 'low_liquidity';if(v<1500)return 'low_volume';if(b<12||s<3)return 'insufficient_trades';
 if(b/s<1.5)return 'weak_buy_pressure';if(l/p.marketCap<.08)return 'shallow_liquidity';return null;
}
export function market(p,now){return marketReason(p,now)===null;}
function snap(p,t){const price=typeof p.priceUsd==='string'?Number(p.priceUsd):p.priceUsd;return finite(price)&&price>0?{t,mint:p.baseToken.address,price,lp:p.liquidity.usd,volume:p.volume.m5,buys:p.txns.m5.buys,sells:p.txns.m5.sells,created:p.pairCreatedAt/1000,symbol:p.baseToken.symbol}:null;}
export function assess(p,rows,now){
 const reason=marketReason(p,now);if(reason)return {reason};
 const cur=snap(p,now),m5=p.priceChange?.m5,h1=p.priceChange?.h1;
 if(!cur||!finite(m5)||!finite(h1))return {reason:'momentum_data_missing'};
 if(m5<0||h1< -15)return {reason:'falling_momentum'};
 if(m5>80)return {reason:'overextended_5m'};
 const base=(rows||[]).filter(r=>r.mint===cur.mint&&finite(r.t)&&now-r.t>=120&&now-r.t<=480&&finite(r.price)&&r.price>0&&finite(r.lp)&&r.lp>0&&finite(r.volume)&&r.volume>0&&Number.isInteger(r.buys)&&r.buys>=0).sort((a,b)=>b.t-a.t)[0];
 if(!base)return {reason:'awaiting_2m_comparison'};
 const change=100*(cur.price/base.price-1),retention=cur.lp/base.lp,growth=cur.volume/base.volume;
 if(change>40)return {reason:'price_ran_ahead_of_baseline'};if(change<0)return {reason:'price_falling_since_baseline'};
 if(retention<.9)return {reason:'liquidity_withdrawal'};
 const share=cur.buys/(cur.buys+p.txns.m5.sells);
 const continuation=growth>=.9&&cur.volume>=10000&&cur.buys>=50&&share>=.62&&cur.lp>=15000;
 if(growth<1.1&&!continuation)return {reason:'volume_not_building'};
 if(cur.buys<base.buys*.9)return {reason:'buy_activity_fading'};
 const clamp=x=>Math.max(0,Math.min(x,1));
 const parts=[25*clamp((share-.5)/.25),25*Math.min(growth/1.5,1),20*Math.min(cur.lp/p.marketCap/.15,1),15*Math.min(cur.buys/30,1),15*Math.max(1-change/80,0)];
 const score=Math.round(parts.reduce((a,b)=>a+Math.round(b*100)/100,0)*10)/10;
 if(score<70)return {reason:'score_below_70',score};
 return {reason:null,score,growth,retention,change,minutes:(now-base.t)/60,level:score>=85?'Momentum kuat':'Momentum berkembang',signal:growth>=1.1?'volume_bertumbuh':'aktivitas_kuat_bertahan'};
}
export function quality(p,rows,now){const q=assess(p,rows,now);return q.reason===null?q:null;}
export function observePerformance(entry,p,now){
 const price=typeof p?.priceUsd==='string'?Number(p.priceUsd):p?.priceUsd;
 if(!p||p.chainId!=='solana'||p.pairAddress!==entry.pair||p.baseToken?.address!==entry.mint||!finite(price)||price<=0||!finite(p.liquidity?.usd)||p.liquidity.usd<0||!finite(entry.alertPrice)||entry.alertPrice<=0)return null;
 const high=Math.max(entry.high||entry.alertPrice,price),low=Math.min(entry.low||entry.alertPrice,price);
 return {...entry,lastPrice:price,lastAt:now,high,low,liquidity:p.liquidity.usd,gain:100*(price/entry.alertPrice-1),peakGain:100*(high/entry.alertPrice-1),worstGain:100*(low/entry.alertPrice-1)};
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
 let count=0;const upstreamErrors=[];
 async function json(url,init={}){if(++count>38)throw Error('request_budget');const r=await fetch(url,{...init,headers:{'User-Agent':'Mozilla/5.0 (compatible; SolanaScreening/1.0)',...(init.headers||{})},signal:AbortSignal.timeout(10000)});if(!r.ok){upstreamErrors.push({host:new URL(url).hostname,status:r.status});throw Error('http_'+r.status);}return r.json();}
 async function rpc(method,params){const j=await json(env.SOLANA_RPC_URL||'https://api.mainnet-beta.solana.com',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});if(j.error||j.result===undefined)throw Error('rpc_rejected');return j.result;}
 async function tg(method,data){const j=await json('https://api.telegram.org/bot'+env.TELEGRAM_BOT_TOKEN+'/'+method,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!j.ok)throw Error('telegram_rejected');return j.result;}
 return {json,rpc,tg,count:()=>count,errors:()=>upstreamErrors};
}
async function discover(c,state={},now=Math.floor(Date.now()/1000)){
 const pools=new Map(),mints=new Set();
 // Keyless discovery costs one credit per request. Once/6m is <=7,200/30d; aligned with 3m KV checkpoints.
 // Keep only pool addresses; never substitute this source's metrics for DEX validation.
 const cache=state.discovery||{at:0,pools:[]};
 if(Math.floor(now/60)%6===0&&now-cache.at>=300&&now>=(cache.blockedUntil||0)){
  cache.at=now;
  try{const j=await c.json('https://api.dexpaprika.com/networks/solana/pools/search?order_by=created_at&sort=desc&limit=50&created_after=-10m&liquidity_usd_min=5000');cache.pools=(j.results||[]).filter(p=>p.chain==='solana'&&key(p.id)&&finite(Date.parse(p.created_at))&&now-Date.parse(p.created_at)/1000>=0&&now-Date.parse(p.created_at)/1000<=600).map(p=>({id:p.id,created:Date.parse(p.created_at)/1000}));}
  catch(e){if(e.message==='http_402')cache.blockedUntil=now+2592000;else if(e.message==='http_403')cache.blockedUntil=now+86400;}
 }
 cache.pools=(cache.pools||[]).filter(p=>now-p.created>=0&&now-p.created<=600);state.discovery=cache;
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
async function track(c,env,state,status,now,pools){
 const entries=(state.alerts||[]).filter(e=>finite(e.alertAt)&&now-e.alertAt>=0&&now-e.alertAt<604800&&Number.isInteger(e.messageId)&&e.messageId>0).slice(-200);
 const active=entries.filter(e=>now-e.alertAt<=86400).slice(-40),market=new Map();
 await refreshPairs(c,active.map(e=>e.pair),market);let edits=0;
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
  edits++;e.announcedUp=up;e.announcedDown=down;e.updateStatus='unconfirmed';
  try{await c.tg('editMessageText',{chat_id:env.TELEGRAM_CHAT_ID,message_id:e.messageId,text:e.body+performanceText(e),parse_mode:'HTML',disable_web_page_preview:true});e.updateStatus='confirmed';status.performanceUpdates++;}catch{status.errors++;}
 }
 status.tracked=active.length;
}
async function run(env,scheduled=true){
 const now=Math.floor(Date.now()/1000),c=await context(env),day=new Date().toISOString().slice(0,10);
 const status={at:now,scheduled,mode:'always_on',engine:'momentum_v2.1',enabled:true,checked:0,passed:0,sent:0,errors:0,rejected:{},performanceUpdates:0};
 const reject=reason=>{status.rejected[reason]=(status.rejected[reason]||0)+1;};
 let state={observations:{},alerts:[]};
 try{
  state=await env.SCANNER_STATE.get('history','json')||state;
  const pools=new Map();await track(c,env,state,status,now,pools);
  const discovered=await discover(c,state,now);status.discovered=discovered.size;status.extraSourcePools=state.discovery?.pools?.length||0;
  for(const [id,p]of discovered)pools.set(id,p);
  const rows=state.observations||{};
  const watched=Object.entries(rows).filter(([,r])=>r.length&&now-r.at(-1).t<900).sort((a,b)=>b[1].at(-1).t-a[1].at(-1).t).map(([id])=>id).filter(id=>!pools.has(id)).slice(0,40);
  await refreshPairs(c,watched,pools);
  status.refreshedPools=pools.size;if(!pools.size){status.error='no_market_data';status.errors++;}
  const ranked=[],samples=[];status.newPools=0;
  for(const p of pools.values()){
   const q=assess(p,rows[p.pairAddress],now);if(q.reason)reject(q.reason);else ranked.push({p,q});
   const age=now-p.pairCreatedAt/1000;
   if(p?.chainId==='solana'&&key(p.pairAddress)&&key(p.baseToken?.address)&&finite(p.pairCreatedAt)&&age>=0&&age<=600&&finite(p.liquidity?.usd)&&p.liquidity.usd>0&&finite(p.volume?.m5)&&p.volume.m5>=0&&Number.isInteger(p.txns?.m5?.buys)&&p.txns.m5.buys>=0&&Number.isInteger(p.txns?.m5?.sells)&&p.txns.m5.sells>=0){
    status.newPools++;
    samples.push({pair:p.pairAddress,mint:p.baseToken.address,symbol:p.baseToken.symbol,at:now,poolAgeMinutes:Math.round(age/6)/10,liquidity:p.liquidity.usd,volume5m:p.volume.m5,buys:p.txns.m5.buys,sells:p.txns.m5.sells,price:snap(p,now)?.price||null,score:q.score||null,reason:q.reason||'awaiting_security',security:'not_checked'});
    const s=snap(p,now);if(s){const r=(rows[p.pairAddress]||[]).filter(x=>now-x.t<=1800);if(!r.length||now-r.at(-1).t>=60)r.push(s);rows[p.pairAddress]=r.slice(-12);}
   }
  }
  status.qualityCandidates=ranked.length;
  ranked.sort((a,b)=>b.q.score-a.q.score);
  const unique=new Set(),candidates=ranked.filter(x=>{const mint=x.p.baseToken.address;if(unique.has(mint))return false;unique.add(mint);return true;}).slice(0,5),alerts=[];
  const daily=await env.SCANNER_STATE.get('deliveries:'+day,'json')||{count:0,mints:[]};
  let accounts=[];if(candidates.length&&c.count()<=31)try{accounts=(await c.rpc('getMultipleAccounts',[candidates.map(x=>x.p.baseToken.address),{encoding:'base64',commitment:'confirmed'}])).value||[];}catch{status.errors++;reject('rpc_mint_unavailable');}
  for(let i=0;i<candidates.length;i++){
   const {p}=candidates[i],mint=p.baseToken.address,sample=samples.find(x=>x.pair===p.pairAddress);
   if(daily.mints.includes(mint)){reject('already_alerted');continue;}
   if(c.count()>31){reject('complete_check_budget_exhausted');continue;}
   status.checked++;
   const fail=reason=>{reject(reason);if(sample){sample.reason=reason;sample.security='not_passed';}};
   try{
    if(!mintSafe(accounts[i])){fail('mint_security_not_verified');continue;}
    const supply=(await c.rpc('getTokenSupply',[mint,{commitment:'confirmed'}])).value?.amount;
    const holders=(await c.rpc('getTokenLargestAccounts',[mint,{commitment:'confirmed'}])).value;
    if(typeof supply!=='string'||!/^[0-9]+$/.test(supply)||BigInt(supply)<=0n||!Array.isArray(holders)||holders.length<10||!holders.slice(0,10).every(x=>typeof x.amount==='string'&&/^[0-9]+$/.test(x.amount))){fail('holder_data_incomplete');continue;}
    const top=holders.slice(0,10).reduce((a,x)=>a+BigInt(x.amount),0n);
    if(top*100n>BigInt(supply)*30n){fail('top10_accounts_over_30pct');continue;}
    const rug=await c.json('https://api.rugcheck.xyz/v1/tokens/'+mint+'/report/summary');
    if(!Array.isArray(rug.risks)||rug.risks.some(x=>typeof x.level!=='string'||['danger','critical'].includes(x.level.toLowerCase()))||!finite(rug.score_normalised)||rug.score_normalised<0||rug.score_normalised>=60){fail('rugcheck_not_passed');continue;}
    const fresh=await c.json(DEX+'/latest/dex/pairs/solana/'+p.pairAddress),observedAt=Math.floor(Date.now()/1000);
    const latest=fresh.pairs?.find(x=>x.pairAddress===p.pairAddress&&x.baseToken?.address===mint),q=quality(latest,rows[p.pairAddress],observedAt);
    if(!q){fail('fresh_momentum_not_passed');continue;}
    alerts.push({p:latest,q,top:Number(top*10000n/BigInt(supply))/100,observedAt});status.passed++;
    if(sample){sample.security='passed';sample.reason='ready';sample.score=q.score;}
   }catch{status.errors++;fail('security_request_failed');}
  }
  for(const {p,q,top,observedAt}of alerts.slice(0,5)){
   if(daily.count>=200||c.count()>=38)break;
   if(!market(p,Date.now()/1000)||Date.now()/1000-observedAt>30){reject('market_snapshot_expired_before_send');continue;}
   const mint=p.baseToken.address,price=snap(p,now)?.price;
   if(!finite(price)||price<=0){reject('alert_price_missing');continue;}
   daily.count++;daily.mints.push(mint);
   await env.SCANNER_STATE.put('deliveries:'+day,JSON.stringify(daily),{expirationTtl:172800});
   const text=`MOMENTUM SOLANA · ${esc(p.baseToken.symbol)}\n${q.level} · skor ${q.score}/100 (skor aturan, bukan probabilitas)\nHarga saat alert $${price.toPrecision(6)} · MCap $${Math.round(p.marketCap)}\nUmur pool ${Math.floor((Date.now()-p.pairCreatedAt)/60000)} menit (umur mint belum diverifikasi)\nLikuiditas $${Math.round(p.liquidity.usd)} · Volume 5m $${Math.round(p.volume.m5)}\nBUY/SELL 5m ${p.txns.m5.buys}/${p.txns.m5.sells}\nVolume ${q.growth.toFixed(2)}x pembanding ${q.minutes.toFixed(1)} menit · retensi LP ${(q.retention*100).toFixed(1)}%\nTop 10 akun token ${top}% (bukan wallet unik)\nMint/freeze authority nonaktif; RugCheck lolos pada waktu pemeriksaan.\nMint: <code>${mint}</code>\n<a href="https://axiom.trade/t/${mint}">Axiom</a> · <a href="https://dexscreener.com/solana/${p.pairAddress}">Chart</a>\nRisiko tetap tinggi; tidak menjamin kenaikan. Tanpa trading otomatis.`;
   const r=await c.tg('sendMessage',{chat_id:env.TELEGRAM_CHAT_ID,text,parse_mode:'HTML',disable_web_page_preview:true}),alertAt=Math.floor(Date.now()/1000);
   if(!Number.isInteger(r.message_id)||r.message_id<=0)throw Error('missing_delivery_receipt');
   status.sent++;state.alerts=state.alerts||[];
   state.alerts.push({mint,pair:p.pairAddress,symbol:p.baseToken.symbol,alertPrice:price,alertAt,observedAt,messageId:r.message_id,score:q.score,high:price,low:price,lastPrice:price,lastAt:alertAt,gain:0,peakGain:0,worstGain:0,announcedUp:0,announcedDown:0,tracking:'active',body:text});
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
  const path=new URL(request.url).pathname;if(path==='/health')return Response.json({service:'solana-screening',engine:'momentum_v2.1',configured:!!env.SCANNER_STATE});
  if(path==='/data'){const s=await env.SCANNER_STATE.get('history','json')||{};return Response.json({status:s.status||{pending:true},samples:s.samples||[],results:(s.alerts||[]).map(({body,...entry})=>entry),note:'Samples are observations, not approved signals. Results exist only after a confirmed Telegram alert; price samples are not realised trading profit.'},{headers:{'Cache-Control':'no-store'}});}
  if(request.headers.get('Authorization')!=='Bearer '+env.DEPLOY_CHECK_KEY)return new Response('Forbidden',{status:403});
  if(path==='/admin/probe'&&request.method==='POST'){const c=await context(env),s=await env.SCANNER_STATE.get('history','json')||{},pools=await discover(c,s),rejected={},qualified=[];for(const p of pools.values()){const q=assess(p,s.observations?.[p.pairAddress],Date.now()/1000);if(q.reason)rejected[q.reason]=(rejected[q.reason]||0)+1;else qualified.push({symbol:p.baseToken.symbol,mint:p.baseToken.address,score:q.score,security:'not_checked'});}return Response.json({pools:pools.size,rejected,qualified,upstreamErrors:c.errors(),requests:c.count()});}
  if(path==='/admin/status')return Response.json((await env.SCANNER_STATE.get('history','json'))?.status||{pending:true});
  if(path==='/admin/test'&&request.method==='POST'){
   try{const c=await context(env),chat=await c.tg('getChat',{chat_id:env.TELEGRAM_CHAT_ID});if(!['channel','group','supergroup'].includes(chat.type))throw Error('unsupported_chat');const r=await c.tg('sendMessage',{chat_id:env.TELEGRAM_CHAT_ID,text:'UJI KONEKSI MOMENTUM V2 — scanner selalu aktif setiap 1 menit. Kandidat wajib lolos data pasar, pembanding momentum minimal 2 menit, mint/freeze, konsentrasi akun token, dan RugCheck. Harga alert serta perkembangan naik/turun akan dicatat setelah pengiriman kandidat berhasil. Pesan ini hanya uji koneksi; belum membuktikan adanya kandidat atau kenaikan harga.'});console.log(JSON.stringify({event:'telegram_test_sent',message_id:r.message_id,chat_type:chat.type}));return Response.json({ok:true,message_id:r.message_id,chat_type:chat.type,chat_title:chat.title});}catch{return Response.json({ok:false,error:'telegram_test_failed'},{status:502});}
  }
  return new Response('Not found',{status:404});
 }
};

