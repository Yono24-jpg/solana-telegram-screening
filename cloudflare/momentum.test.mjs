import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker,{quality,assess,observePerformance,performanceText} from './worker.mjs';
const now=1800000000,mint='B'.repeat(44),pair='A'.repeat(44);
const pool=()=>({chainId:'solana',pairAddress:pair,baseToken:{address:mint,symbol:'FIXTURE'},pairCreatedAt:(now-500)*1000,priceUsd:'1',liquidity:{usd:20000},marketCap:100000,volume:{m5:4000},txns:{m5:{buys:40,sells:10}},priceChange:{m5:35,h1:179}});
const baseline=()=>[{t:now-120,mint,price:.98,lp:20000,volume:2000,buys:30}];
test('accept developing momentum above old 15 percent cap with measured two-minute baseline',()=>{assert.ok(quality(pool(),baseline(),now)?.score>=70);const r=baseline();r[0].t=now-119;assert.equal(assess(pool(),r,now).reason,'awaiting_2m_comparison');});
test('support sustained high activity and retain withdrawal/overextension guards',()=>{const p=pool(),r=baseline();p.volume.m5=20000;p.txns.m5={buys:80,sells:25};r[0].volume=22000;r[0].buys=80;assert.ok(quality(p,r,now));r[0].lp=30000;assert.equal(assess(p,r,now).reason,'liquidity_withdrawal');r[0].lp=20000;r[0].price=.5;assert.equal(assess(p,r,now).reason,'price_ran_ahead_of_baseline');});
test('performance records losses and strict mint/pair identity; never manufactures success',()=>{const e={pair,mint,alertPrice:1,high:1,low:1},p=pool();p.priceUsd='.4';const r=observePerformance(e,p,now);assert.ok(Math.abs(r.gain+60)<1e-8);assert.equal(r.peakGain,0);assert.ok(Math.abs(r.worstGain+60)<1e-8);assert.match(performanceText(r),/-60.0%/);p.baseToken.address='C'.repeat(44);assert.equal(observePerformance(e,p,now),null);});
async function scanFixture({holdersMissing=false,rugUnavailable=false,trackedPrice=null,profilesEmpty=false,discoveryKey=null,discoveryPlan='free'}={}){
 const oldFetch=globalThis.fetch,oldNow=Date.now,storage=new Map([['history',{observations:{[pair]:baseline()},alerts:[]}]]),messages=[];
 const b=new Uint8Array(82);b[45]=1;
 const account={owner:'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',executable:false,data:[Buffer.from(b).toString('base64'),'base64']};
 if(trackedPrice!==null)storage.get('history').alerts=[{mint,pair,symbol:'FIXTURE',alertAt:now-600,messageId:123,alertPrice:1,high:1,low:1,lastPrice:1,lastAt:now-600,body:'Confirmed fixture alert'}];
 Date.now=()=>now*1000;
 globalThis.fetch=async(url,init={})=>{
  url=String(url);
  if(discoveryKey){if(url.includes('api.dexpaprika.com'))assert.equal(init.headers.Authorization,discoveryKey);else assert.equal(init.headers.Authorization,undefined);}
  if(url.includes('telegram.org')){messages.push(JSON.parse(init.body));return Response.json({ok:true,result:{message_id:321}});}
  if(url.includes('mainnet-beta')){const {method}=JSON.parse(init.body);let result;
   if(method==='getMultipleAccounts')result={value:[account]};
   if(method==='getTokenSupply')result={value:{amount:'1000'}};
   if(method==='getTokenLargestAccounts')result={value:holdersMissing?[]:Array.from({length:10},()=>({amount:'10'}))};
   return Response.json({jsonrpc:'2.0',id:1,result});
  }
  if(url.includes('rugcheck'))return rugUnavailable?new Response('unavailable',{status:429}):Response.json({risks:[],score_normalised:5});
  if(url.includes('geckoterminal'))return Response.json({data:[]});
  if(url.includes('dexpaprika'))return Response.json({results:[{chain:'solana',id:pair,created_at:new Date((now-500)*1000).toISOString(),price_usd:99999},{chain:'ethereum',id:'C'.repeat(44),created_at:new Date(now*1000).toISOString()}]},{headers:{'x-api-plan':discoveryPlan}});
  if(url.includes('/latest/dex/pairs/'))return Response.json({pairs:[{...pool(),priceUsd:String(trackedPrice??1)}]});
  if(url.includes('/tokens/v1/'))return Response.json([{...pool(),priceUsd:String(trackedPrice??1)}]);
  return Response.json(profilesEmpty?[]:[{chainId:'solana',tokenAddress:mint}]);
 };
 try{const env={SCANNER_STATE:{get:async(k)=>storage.get(k)||null,put:async(k,v)=>storage.set(k,JSON.parse(v))},TELEGRAM_BOT_TOKEN:'fixture',TELEGRAM_CHAT_ID:'fixture',DEXPAPRIKA_API_KEY:discoveryKey};let pending;await worker.scheduled({},env,{waitUntil:p=>{pending=p;}});await pending;return {state:storage.get('history'),messages};}
 finally{globalThis.fetch=oldFetch;Date.now=oldNow;}
}
test('complete verified pipeline records the actual receipt and initial price only after delivery',async()=>{const r=await scanFixture();assert.equal(r.messages.length,1);assert.equal(r.state.status.passed,1);assert.equal(r.state.status.sent,1);assert.equal(r.state.alerts[0].messageId,321);assert.equal(r.state.alerts[0].alertPrice,1);assert.equal(r.state.alerts[0].gain,0);assert.equal(r.messages[0].reply_markup,undefined);});
test('missing holder data or failed RugCheck cannot send or create performance records',async()=>{for(const options of [{holdersMissing:true},{rugUnavailable:true}]){const r=await scanFixture(options);assert.equal(r.messages.length,0);assert.equal(r.state.alerts.length,0);assert.equal(r.state.status.sent,0);}});
test('tracking a confirmed alert reports a loss in the original message and does not create a new signal',async()=>{const r=await scanFixture({trackedPrice:.4});assert.equal(r.state.status.sent,0);assert.equal(r.state.status.performanceUpdates,1);assert.equal(r.messages.length,1);assert.equal(r.messages[0].message_id,123);assert.match(r.messages[0].text,/-60.0%/);assert.equal(r.state.alerts.length,1);assert.equal(r.state.alerts[0].tracking,'active');});
test('extra discovery normalizes pool identity and still requires complete independent security',async()=>{const r=await scanFixture({profilesEmpty:true});assert.equal(r.state.discovery.pools.length,1);assert.equal(r.state.status.extraSourcePools,1);assert.equal(r.state.status.sent,1);assert.equal(r.state.alerts[0].alertPrice,1);const denied=await scanFixture({profilesEmpty:true,rugUnavailable:true});assert.equal(denied.state.status.sent,0);assert.equal(denied.state.alerts.length,0);});
test('discovery credential is scoped to its host and must be recognized as the free plan',async()=>{const r=await scanFixture({profilesEmpty:true,discoveryKey:'api_fixture'});assert.equal(r.state.status.sent,1);assert.equal(r.state.discovery.authenticated,true);const denied=await scanFixture({profilesEmpty:true,discoveryKey:'api_fixture',discoveryPlan:'keyless'});assert.equal(denied.state.discovery.pools.length,0);assert.equal(denied.state.status.extraSourcePools,0);assert.equal(denied.state.discovery.error,'discovery_key_not_verified_free');});
