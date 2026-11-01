import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker from './worker.mjs';
test('HTTP 429 stops repeated provider requests and preserves Retry-After for the next cron',async()=>{
 const oldFetch=globalThis.fetch,oldNow=Date.now,store=new Map();let now=1800000000,dexCalls=0;
 Date.now=()=>now*1000;
 globalThis.fetch=async url=>{if(String(url).includes('dexscreener.com')){dexCalls++;return new Response('limit',{status:429,headers:{'Retry-After':'120'}});}return Response.json({data:[],results:[]});};
 const env={SCANNER_STATE:{get:async k=>store.has(k)?structuredClone(store.get(k)):null,put:async(k,v)=>store.set(k,JSON.parse(v))}};
 try{
  let pending;await worker.scheduled({},env,{waitUntil:p=>{pending=p;}});await pending;
  assert.equal(dexCalls,1);assert.equal(store.get('history').cooldowns['api.dexscreener.com'],now+120);
  now+=60;await worker.scheduled({},env,{waitUntil:p=>{pending=p;}});await pending;assert.equal(dexCalls,1);
  now+=60;await worker.scheduled({},env,{waitUntil:p=>{pending=p;}});await pending;assert.equal(dexCalls,2);
 }finally{globalThis.fetch=oldFetch;Date.now=oldNow;}
});
test('edge cooldown covers Retry-After when the first failure is between KV checkpoints',async()=>{
 const oldFetch=globalThis.fetch,oldNow=Date.now,oldCaches=globalThis.caches,edge=new Map();let now=1800000060,calls=0;
 Date.now=()=>now*1000;
 globalThis.caches={default:{match:async r=>edge.get(r.url)?.clone(),put:async(r,v)=>edge.set(r.url,v.clone())}};
 globalThis.fetch=async url=>{if(String(url).includes('dexscreener.com')){calls++;return new Response('limit',{status:429,headers:{'Retry-After':'120'}});}return Response.json({data:[],results:[]});};
 const env={SCANNER_STATE:{get:async()=>null,put:async()=>{}}};
 try{let pending;await worker.scheduled({},env,{waitUntil:p=>{pending=p;}});await pending;assert.equal(calls,1);now+=60;await worker.scheduled({},env,{waitUntil:p=>{pending=p;}});await pending;assert.equal(calls,1);}
 finally{globalThis.fetch=oldFetch;Date.now=oldNow;if(oldCaches===undefined)delete globalThis.caches;else globalThis.caches=oldCaches;}
});
