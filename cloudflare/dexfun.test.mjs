import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker,{normalizeDexFunLaunches} from './worker.mjs';

const now=1800000000,nowMs=now*1000,mint='A'.repeat(44),other='B'.repeat(44);
const envelope=(data,stale=false,asOf=nowMs)=>({data,stale,asOf});

test('Dex.fun launch seeds require fresh envelopes and use launch or graduation time by stage',()=>{
 const fresh=envelope([
  {mint,symbol:'NEW',stage:'new',createdAt:nowMs-300000},
  {mint:other,symbol:'OLD',stage:'new',createdAt:nowMs-700000},
  {mint:'C'.repeat(44),symbol:'WRONG',stage:'graduated',createdAt:nowMs-1000}
 ]);
 assert.deepEqual(normalizeDexFunLaunches(fresh,'new',nowMs),[mint]);
 assert.deepEqual(normalizeDexFunLaunches(envelope([{mint:other,symbol:'BONDING',stage:'bonding',createdAt:nowMs-300000}]),'bonding',nowMs),[other]);
 assert.deepEqual(normalizeDexFunLaunches(envelope([{mint,symbol:'MIGRATED',stage:'graduated',graduatedAt:nowMs-300000}]),'graduated',nowMs),[mint]);
});

test('Dex.fun stale, incomplete, future, or old launch snapshots fail closed',()=>{
 const row={mint,symbol:'NEW',stage:'new',createdAt:nowMs-1000};
 assert.deepEqual(normalizeDexFunLaunches(envelope([row],true),'new',nowMs),[]);
 assert.deepEqual(normalizeDexFunLaunches(envelope([row],false,nowMs-91000),'new',nowMs),[]);
 assert.deepEqual(normalizeDexFunLaunches(envelope([{...row,createdAt:nowMs+10000}]),'new',nowMs),[]);
 assert.deepEqual(normalizeDexFunLaunches(envelope([{...row,createdAt:nowMs-601000}]),'new',nowMs),[]);
 assert.deepEqual(normalizeDexFunLaunches({data:[row],asOf:nowMs},'new',nowMs),[]);
});

test('launch scan sends Dex.fun bearer key only to official host and keeps final checks on existing feeds',async()=>{
 const oldFetch=globalThis.fetch,oldNow=Date.now,store=new Map(),seen=[];
 Date.now=()=>nowMs;
 globalThis.fetch=async(url,init={})=>{
  url=String(url);seen.push({url,authorization:init.headers?.Authorization});
  if(url.startsWith('https://data.dex.fun/')){
   assert.equal(init.headers.Authorization,'Bearer test_dexfun_secret');
   const stage=new URL(url).searchParams.get('stage');
   const data=stage==='new'?[{mint,symbol:'NEW',name:'New',stage:'new',createdAt:nowMs-300000}]:stage==='bonding'?[{mint:other,symbol:'BOND',name:'Bonding',stage:'bonding',createdAt:nowMs-240000}]:[];
   return Response.json({data,asOf:nowMs,stale:false});
  }
  assert.notEqual(init.headers?.Authorization,'Bearer test_dexfun_secret');
  if(url.includes('api.dexscreener.com'))return Response.json(url.includes('/tokens/v1/')?[]:{pairs:[]});
  if(url.includes('api.dexpaprika.com'))return Response.json({results:[]},{headers:{'x-api-plan':'keyless'}});
  if(url.includes('geckoterminal'))return Response.json({data:[]});
  throw Error('unexpected_fixture_host');
 };
 try{
  const env={SCANNER_STATE:{get:async k=>store.get(k)||null,put:async(k,v)=>store.set(k,JSON.parse(v))},DEXFUN_API_KEY:'test_dexfun_secret'};
  let pending;await worker.scheduled({},env,{waitUntil:p=>{pending=p;}});await pending;
  const state=store.get('history');
  assert.equal(state.status.dexfun.configured,true);
  assert.equal(state.status.dexfun.newMints,1);
  assert.equal(state.status.dexfun.bondingMints,1);
  assert.equal(state.status.dexfun.graduatedMints,0);
  assert.ok(seen.filter(x=>x.url.startsWith('https://data.dex.fun/')).length===3);
  assert.ok(seen.filter(x=>x.authorization).every(x=>x.url.startsWith('https://data.dex.fun/')));
  assert.equal(JSON.stringify(state.status).includes('test_dexfun_secret'),false);
 }finally{globalThis.fetch=oldFetch;Date.now=oldNow;}
});
