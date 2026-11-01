import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker,{normalizePaprika,market,quality} from './worker.mjs';
const now=1800000000,pair='A'.repeat(44),mint='B'.repeat(44),quote='So11111111111111111111111111111111111111112';
const raw=()=>({id:pair,chain:'solana',base_token_id:mint,quote_token_id:quote,created_at:new Date((now-500)*1000).toISOString(),last_price_usd:1,price_time:new Date((now-10)*1000).toISOString(),last_updated:new Date((now-5)*1000).toISOString(),liquidity_usd:20000,tokens:[{id:quote,symbol:'SOL',fdv:1000000000},{id:mint,symbol:'FIXTURE',fdv:100000}],'5m':{last_price_usd_change:35,volume_usd:4000,buys:40,sells:10},'1h':{last_price_usd_change:179}});
const baseline=()=>[{t:now-180,mint,price:.98,lp:20000,volume:2000,buys:30,sells:10,created:now-500,symbol:'FIXTURE',source:'dexpaprika',providerAt:now-180}];
test('pool detail normalization binds price to explicit base mint and labels valuation as FDV',()=>{const p=normalizePaprika(raw(),pair,now);assert.equal(p.baseToken.address,mint);assert.equal(p.marketCap,undefined);assert.equal(p.fdv,100000);assert.equal(p.priceUsd,'1');assert.equal(market(p,now),true);assert.ok(quality(p,baseline(),now));const r=baseline();r[0].source='dexscreener';assert.equal(quality(p,r,now),null);});
test('reject stale, zero-price, missing-statistics and mismatched pool data',()=>{for(const mutate of [p=>{p.last_price_usd=0;},p=>{p.price_time=new Date((now-121)*1000).toISOString();},p=>{delete p['5m'].sells;},p=>{p.id='C'.repeat(44);},p=>{delete p.tokens[1].fdv;}]){const p=raw();mutate(p);assert.equal(normalizePaprika(p,pair,now),null);}});
async function exercise({rugDanger=false,holdersMissing=false}={}){
 const oldFetch=globalThis.fetch,oldNow=Date.now,store=new Map([['history',{observations:{[pair]:baseline()},alerts:[]}]]),sent=[];let details=0;
 Date.now=()=>now*1000;
 const b=new Uint8Array(82);b[45]=1;const account={owner:'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',executable:false,data:[Buffer.from(b).toString('base64'),'base64']};
 globalThis.fetch=async(url,init={})=>{
  url=String(url);
  if(url.includes('dexscreener'))return new Response('rate limit',{status:429});
  if(url.includes('geckoterminal'))return Response.json({data:[]});
  if(url.includes('dexpaprika')){
   assert.equal(init.headers.Authorization,'api_fixture');
   if(url.includes('/pools/search'))return Response.json({results:[{id:pair,chain:'solana',created_at:raw().created_at,liquidity_usd:20000,volume_usd_24h:10000,price_change_percentage_5m:35}]},{headers:{'x-api-plan':'free'}});
   details++;return Response.json(raw(),{headers:{'x-api-plan':'free'}});
  }
  if(url.includes('mainnet-beta')){const {method}=JSON.parse(init.body);const result=method==='getMultipleAccounts'?{value:[account]}:method==='getTokenSupply'?{value:{amount:'1000'}}:{value:holdersMissing?[]:Array.from({length:10},()=>({amount:'10'}))};return Response.json({result});}
  if(url.includes('rugcheck'))return Response.json({risks:rugDanger?[{level:'danger'}]:[],score_normalised:rugDanger?80:5});
  if(url.includes('telegram')){sent.push(JSON.parse(init.body));return Response.json({ok:true,result:{message_id:456}});}
  throw Error('unexpected_fixture_host');
 };
 try{const env={SCANNER_STATE:{get:async k=>store.has(k)?structuredClone(store.get(k)):null,put:async(k,v)=>store.set(k,JSON.parse(v))},DEXPAPRIKA_API_KEY:'api_fixture',TELEGRAM_BOT_TOKEN:'fixture',TELEGRAM_CHAT_ID:'fixture'};let pending;await worker.scheduled({},env,{waitUntil:p=>{pending=p;}});await pending;return {state:store.get('history'),sent,details};}
 finally{globalThis.fetch=oldFetch;Date.now=oldNow;}
}
test('complete authenticated fallback can deliver only after all security and a fresh second market read',async()=>{const r=await exercise();assert.equal(r.sent.length,1);assert.equal(r.details,2);assert.equal(r.state.status.sent,1);assert.equal(r.state.alerts[0].messageId,456);assert.equal(r.state.alerts[0].priceSource,'dexpaprika');assert.match(r.sent[0].text,/FDV \$100000/);assert.doesNotMatch(r.sent[0].text,/MCap/);});
test('fallback never sends when RugCheck or holder completeness fails',async()=>{for(const options of [{rugDanger:true},{holdersMissing:true}]){const r=await exercise(options);assert.equal(r.sent.length,0);assert.equal(r.state.alerts.length,0);assert.equal(r.details,1);}});
