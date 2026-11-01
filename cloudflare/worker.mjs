// Separate Cloudflare scanner. Never installs a Telegram webhook or consumes updates.
const DEX='https://api.dexscreener.com';
const STATE_URL='https://raw.githubusercontent.com/Yono24-jpg/solana-telegram-screening/main/state.json';
const KEYBOARD={inline_keyboard:[[{text:'ON',callback_data:'on'},{text:'OFF',callback_data:'off'}]]};
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const key=x=>typeof x==='string'&&/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(x);
const esc=x=>String(x).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
export function market(p,now){
 if(p?.chainId!=='solana'||!key(p.pairAddress)||!key(p.baseToken?.address)||typeof p.baseToken.symbol!=='string')return false;
 const age=now-p.pairCreatedAt/1000,l=p.liquidity?.usd,v=p.volume?.m5,b=p.txns?.m5?.buys,s=p.txns?.m5?.sells;
 return finite(p.pairCreatedAt)&&age>=300&&age<=10800&&finite(l)&&l>=10000&&finite(v)&&v>=1500&&Number.isInteger(b)&&b>=12&&Number.isInteger(s)&&s>=3&&b/Math.max(s,1)>=1.5&&finite(p.marketCap)&&p.marketCap>0&&l/p.marketCap>=.08;
}
function snap(p,t){const price=typeof p.priceUsd==='string'?Number(p.priceUsd):p.priceUsd;return finite(price)&&price>0?{t,mint:p.baseToken.address,price,lp:p.liquidity.usd,volume:p.volume.m5,buys:p.txns.m5.buys}:null;}
export function quality(p,rows,now){
 if(!market(p,now))return null;
 const cur=snap(p,now),m5=p.priceChange?.m5,h1=p.priceChange?.h1;
 if(!cur||!finite(m5)||!finite(h1)||m5<0||m5>15||h1< -15||h1>60)return null;
 const base=(rows||[]).filter(r=>r.mint===cur.mint&&finite(r.t)&&now-r.t>=300&&now-r.t<=900&&finite(r.price)&&r.price>0&&finite(r.lp)&&r.lp>0&&finite(r.volume)&&r.volume>0&&Number.isInteger(r.buys)).sort((a,b)=>b.t-a.t)[0];
 if(!base)return null;
 const change=100*(cur.price/base.price-1),retention=cur.lp/base.lp,growth=cur.volume/base.volume;
 if(change>15||change< -5||retention<.9||growth<1.1||cur.buys<base.buys)return null;
 const share=cur.buys/(cur.buys+p.txns.m5.sells),clamp=x=>Math.max(0,Math.min(x,1));
 const parts=[25*clamp((share-.5)/.25),25*Math.min(growth/2,1),20*Math.min(cur.lp/p.marketCap/.15,1),15*Math.min(cur.buys/30,1),15*Math.max(1-m5/30,0)];
 const score=Math.round(parts.reduce((a,b)=>a+Math.round(b*100)/100,0)*10)/10;
 return score>=70?{score,growth,retention,change,minutes:(now-base.t)/60}:null;
}
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
 async function json(url,init={}){if(++count>45)throw Error('request_budget');const r=await fetch(url,{...init,headers:{'User-Agent':'Mozilla/5.0 (compatible; SolanaScreening/1.0)',...(init.headers||{})},signal:AbortSignal.timeout(15000)});if(!r.ok){upstreamErrors.push({host:new URL(url).hostname,status:r.status});throw Error('http_'+r.status);}return r.json();}
 async function rpc(method,params){const j=await json(env.SOLANA_RPC_URL||'https://api.mainnet-beta.solana.com',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});if(j.error||j.result===undefined)throw Error('rpc_rejected');return j.result;}
 async function tg(method,data){const j=await json('https://api.telegram.org/bot'+env.TELEGRAM_BOT_TOKEN+'/'+method,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!j.ok)throw Error('telegram_rejected');return j.result;}
 return {json,rpc,tg,count:()=>count,errors:()=>upstreamErrors};
}
async function discover(c){
 const pools=new Map(),mints=new Set();
 for(const path of ['/token-profiles/latest/v1','/token-boosts/latest/v1'])try{const a=await c.json(DEX+path);if(Array.isArray(a))for(const t of a)if(t.chainId==='solana'&&key(t.tokenAddress)&&mints.size<90)mints.add(t.tokenAddress);}catch{}
 const add=a=>{if(Array.isArray(a))for(const p of a)if(key(p?.pairAddress))pools.set(p.pairAddress,p);};
 const list=[...mints];for(let i=0;i<list.length;i+=30)try{add(await c.json(DEX+'/tokens/v1/solana/'+list.slice(i,i+30).join(',')));}catch{}
 for(let page=1;page<=2;page++)try{const g=await c.json('https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page='+page);const pairs=(g.data||[]).map(x=>x.attributes?.address).filter(key);for(let i=0;i<pairs.length;i+=20){const d=await c.json(DEX+'/latest/dex/pairs/solana/'+pairs.slice(i,i+20).join(','));add(d.pairs);}}catch{}
 return pools;
}
async function run(env,scheduled=true){
 const now=Math.floor(Date.now()/1000),c=await context(env),day=new Date().toISOString().slice(0,10);
 const status={at:now,scheduled,enabled:false,checked:0,passed:0,sent:0,errors:0};
 try{
  // Old bot remains the sole callback consumer; unavailable/invalid shared state means OFF.
  const control=await c.json(STATE_URL+'?minute='+Math.floor(now/60),{headers:{'Cache-Control':'no-cache'}});
  if(typeof control.enabled!=='boolean')throw Error('control_unverified');status.enabled=control.enabled;
  const state=await env.SCANNER_STATE.get('history','json')||{observations:{}};
  if(status.enabled){
   const pools=await discover(c),rows=state.observations||{},ranked=[];
   status.discovered=pools.size;if(!pools.size){status.error='no_market_data';status.errors++;}
   for(const p of pools.values())if(market(p,now)){
    const q=quality(p,rows[p.pairAddress],now);if(q)ranked.push({p,q});
    const s=snap(p,now);if(s){const r=(rows[p.pairAddress]||[]).filter(x=>now-x.t<=1800);if(!r.length||now-r.at(-1).t>=60)r.push(s);rows[p.pairAddress]=r.slice(-12);}
   }
   // A hard budget leaves room for complete security checks and fresh market data.
   ranked.sort((a,b)=>b.q.score-a.q.score);const candidates=ranked.slice(0,4),alerts=[];
   const daily=await env.SCANNER_STATE.get('deliveries:'+day,'json')||{count:0,mints:[]};
   let accounts=[];if(candidates.length)try{accounts=(await c.rpc('getMultipleAccounts',[candidates.map(x=>x.p.baseToken.address),{encoding:'base64',commitment:'confirmed'}])).value||[];}catch{status.errors++;}
   for(let i=0;i<candidates.length;i++){
    const {p}=candidates[i],mint=p.baseToken.address;if(daily.mints.includes(mint))continue;status.checked++;
    try{
     if(!mintSafe(accounts[i]))continue;
     const supply=(await c.rpc('getTokenSupply',[mint,{commitment:'confirmed'}])).value?.amount;
     const holders=(await c.rpc('getTokenLargestAccounts',[mint,{commitment:'confirmed'}])).value;
     if(!/^[0-9]+$/.test(supply)||BigInt(supply)<=0n||!Array.isArray(holders)||holders.length<10)continue;
     if(!holders.slice(0,10).every(x=>typeof x.amount==='string'&&/^[0-9]+$/.test(x.amount)))continue;
     const top=holders.slice(0,10).reduce((a,x)=>a+BigInt(x.amount),0n);if(top*100n>BigInt(supply)*30n)continue;
     const rug=await c.json('https://api.rugcheck.xyz/v1/tokens/'+mint+'/report/summary');
     if(!Array.isArray(rug.risks)||rug.risks.some(x=>typeof x.level!=='string'||['danger','critical'].includes(x.level.toLowerCase()))||!finite(rug.score_normalised)||rug.score_normalised<0||rug.score_normalised>=60)continue;
     const fresh=await c.json(DEX+'/latest/dex/pairs/solana/'+p.pairAddress);const latest=fresh.pairs?.find(x=>x.pairAddress===p.pairAddress&&x.baseToken?.address===mint);const q=quality(latest,rows[p.pairAddress],Date.now()/1000);if(!q)continue;
     alerts.push({p:latest,q,top:Number(top*10000n/BigInt(supply))/100});status.passed++;
    }catch{status.errors++;}
   }
   // 720 history writes + <=200 delivery writes/day keeps this namespace within free KV writes.
   for(const {p,q,top}of alerts.slice(0,5)){
    if(daily.count>=200)break;
    // Reserve before send: a failed or interrupted delivery is never retried automatically.
    daily.count++;daily.mints.push(p.baseToken.address);await env.SCANNER_STATE.put('deliveries:'+day,JSON.stringify(daily),{expirationTtl:172800});
    const text=`Cloudflare · ${esc(p.baseToken.symbol)} · skor ${q.score}/100\nUmur pool ${Math.floor((Date.now()-p.pairCreatedAt)/60000)} menit (umur mint belum diverifikasi)\nLikuiditas $${Math.round(p.liquidity.usd)} · Volume 5m $${Math.round(p.volume.m5)}\nBUY/SELL 5m ${p.txns.m5.buys}/${p.txns.m5.sells}\nPertumbuhan volume ${q.growth.toFixed(2)}x · retensi LP ${(q.retention*100).toFixed(1)}%\nTop 10 akun token ${top}% (bukan jumlah wallet unik)\nMint/freeze authority nonaktif; pemeriksaan RugCheck lolos.\nMint: <code>${p.baseToken.address}</code>\n<a href="https://axiom.trade/t/${p.baseToken.address}">Axiom</a> · <a href="https://dexscreener.com/solana/${p.pairAddress}">Chart</a>\nRisiko tetap tinggi; bukan jaminan aman. Tanpa transaksi otomatis.`;
    const r=await c.tg('sendMessage',{chat_id:env.TELEGRAM_CHAT_ID,text,parse_mode:'HTML',disable_web_page_preview:true,reply_markup:KEYBOARD});status.sent++;console.log(JSON.stringify({event:'telegram_alert_sent',message_id:r.message_id}));
   }
   state.observations=Object.fromEntries(Object.entries(rows).filter(([,r])=>r.some(x=>now-x.t<=1800)).sort((a,b)=>b[1].at(-1).t-a[1].at(-1).t).slice(0,160));
  }
  status.upstreamErrors=c.errors();if(Math.floor(now/60)%2===0){state.status=status;await env.SCANNER_STATE.put('history',JSON.stringify(state));}
 }catch(e){status.errors++;status.error=/^[a-z_0-9]+$/.test(e.message)?e.message:'check_failed';}
 console.log(JSON.stringify({event:'scanner_run',...status,requests:c.count()}));return status;
}
export default{
 async scheduled(event,env,ctx){ctx.waitUntil(run(env,true));},
 async fetch(request,env){
  const path=new URL(request.url).pathname;if(path==='/health')return Response.json({service:'solana-screening',configured:!!env.SCANNER_STATE});
  if(request.headers.get('Authorization')!=='Bearer '+env.DEPLOY_CHECK_KEY)return new Response('Forbidden',{status:403});
  if(path==='/admin/status')return Response.json((await env.SCANNER_STATE.get('history','json'))?.status||{pending:true});
  if(path==='/admin/test'&&request.method==='POST'){
   try{const c=await context(env),chat=await c.tg('getChat',{chat_id:env.TELEGRAM_CHAT_ID});if(!['channel','group','supergroup'].includes(chat.type))throw Error('unsupported_chat');const r=await c.tg('sendMessage',{chat_id:env.TELEGRAM_CHAT_ID,text:'UJI CLOUDFLARE BERHASIL — pesan ini dikirim langsung oleh Worker. Jadwal screening dipasang terpisah. ON/OFF memakai kendali bersama bot GitHub; perubahan mengikuti pemrosesan bot tersebut. Ini pesan uji koneksi, bukan rekomendasi token.',reply_markup:KEYBOARD});console.log(JSON.stringify({event:'telegram_test_sent',message_id:r.message_id,chat_type:chat.type}));return Response.json({ok:true,message_id:r.message_id,chat_type:chat.type,chat_title:chat.title});}catch{return Response.json({ok:false,error:'telegram_test_failed'},{status:502});}
  }
  return new Response('Not found',{status:404});
 }
};
