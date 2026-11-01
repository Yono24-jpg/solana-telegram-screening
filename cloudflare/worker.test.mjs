import {test} from 'node:test';
import assert from 'node:assert/strict';
import {market,quality,mintSafe} from './worker.mjs';
const now=1800000000;
const pool=()=>({chainId:'solana',pairAddress:'A'.repeat(44),baseToken:{address:'B'.repeat(44),symbol:'TEST'},pairCreatedAt:(now-500)*1000,priceUsd:'1',liquidity:{usd:20000},marketCap:100000,volume:{m5:4000},txns:{m5:{buys:40,sells:10}},priceChange:{m5:5,h1:10}});
test('reject stale pool or incomplete metrics',()=>{let p=pool();assert.equal(market(p,now),true);p.pairCreatedAt=(now-601)*1000;assert.equal(market(p,now),false);p=pool();delete p.volume.m5;assert.equal(market(p,now),false);});
test('require historical momentum and reject withdrawn liquidity',()=>{const p=pool(),r=[{t:now-360,mint:p.baseToken.address,price:.98,lp:20000,volume:2000,buys:30}];assert.equal(quality(p,[],now),null);assert.ok(quality(p,r,now)?.score>=70);r[0].lp=30000;assert.equal(quality(p,r,now),null);});
test('reject unknown or malformed mint accounts and active authority',()=>{assert.equal(mintSafe(null),false);const b=new Uint8Array(82);b[45]=1;const a={owner:'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',executable:false,data:[Buffer.from(b).toString('base64'),'base64']};assert.equal(mintSafe(a),true);b[0]=1;a.data[0]=Buffer.from(b).toString('base64');assert.equal(mintSafe(a),false);});
test('reject price surges and invalid numeric values',()=>{const p=pool(),r=[{t:now-360,mint:p.baseToken.address,price:.98,lp:20000,volume:2000,buys:30}];p.priceChange.m5=16;assert.equal(quality(p,r,now),null);p.liquidity.usd='20000';assert.equal(market(p,now),false);});
