import base64
import copy
import json
import struct
import unittest
from unittest.mock import patch
import bot
import evidence
import scanner_v2
import state_store
import vault_checks as v
from test_upgrade import pool as market_pool, sec, social, mint_age, NOW
from screening_rules import market


def key(n): return v.b58encode(bytes([n])*32)
MINT = key(1); QUOTE = 'So11111111111111111111111111111111111111112'; VAULT = key(40)


def account(raw, owner):
    return {'owner':owner,'data':[base64.b64encode(raw).decode(),'base64'],'executable':False}


def mint_account(supply=1000000):
    raw=bytearray(82);struct.pack_into('<Q',raw,36,supply);raw[44]=6;raw[45]=1
    return account(raw,bot.PROGRAM)


def token(authority, amount, mint=MINT, token_program=bot.PROGRAM, extra=b''):
    raw=bytearray(165);raw[:32]=v.key_bytes(mint);raw[32:64]=v.key_bytes(authority)
    struct.pack_into('<Q',raw,64,amount);raw[108]=1
    return account(raw+extra,token_program)


def pool_fixture(program=v.PUMP, quote_side=False, custom_clmm=False):
    ma,mb=(QUOTE,MINT) if quote_side else (MINT,QUOTE)
    va,vb=(key(41),VAULT) if quote_side else (VAULT,key(41))
    put=lambda raw,pos,value:raw.__setitem__(slice(pos,pos+32),v.key_bytes(value))
    if program==v.PUMP:
        raw=bytearray(211);raw[:8]=v.POOL_DISC;raw[8]=254;struct.pack_into('<H',raw,9,0)
        for pos,val in ((11,key(3)),(43,ma),(75,mb),(107,key(5)),(139,va),(171,vb)):put(raw,pos,val)
        pair=v.pda_with_stored_bump([b'pool',raw[9:11],raw[11:43],raw[43:75],raw[75:107]],254,program)
        authority=pair
    elif program==v.CPMM:
        raw=bytearray(637);raw[:8]=v.STATE_DISC
        bump=next(b for b in range(256) if v.pda_with_stored_bump([b'vault_and_lp_mint_auth_seed'],b,program)==v.CPMM_AUTHORITY)
        raw[328]=bump;pair=key(6);authority=v.CPMM_AUTHORITY
        for pos,val in ((72,va),(104,vb),(168,ma),(200,mb),(232,bot.PROGRAM),(264,bot.PROGRAM)):put(raw,pos,val)
    elif program==v.CLMM:
        raw=bytearray(1544);raw[:8]=v.STATE_DISC;raw[8]=254
        for pos,val in ((9,key(3)),(73,ma),(105,mb),(137,va),(169,vb)):put(raw,pos,val)
        extra=b'\x05\0' if custom_clmm else b'';raw[391:393]=extra or b'\0\0'
        pair=v.pda_with_stored_bump([b'pool',raw[9:41],raw[73:105],raw[105:137],extra],254,program);authority=pair
    else:
        raw=bytearray(752);struct.pack_into('<QQ',raw,0,6,254);pair=key(7)
        authority=v.pda_with_stored_bump([b'amm authority'],254,program)
        for pos,val in ((336,va),(368,vb),(400,ma),(432,mb)):put(raw,pos,val)
    pool={'pairAddress':pair,'baseToken':{'address':MINT},'quoteToken':{'address':QUOTE}}
    return pool,account(raw,program),token(authority,800000)


def snapshots(program=v.PUMP):
    pool,pool_account,vault=pool_fixture(program)
    addresses=[VAULT]+[key(41+i) for i in range(19)]
    amounts=[800000]+[10000]*19
    rows=[{'address':k,'amount':str(a)} for k,a in zip(addresses,amounts)]
    largest={'context':{'slot':1000},'value':rows}
    batch={'context':{'slot':1001},'value':[mint_account(),pool_account,vault]+[token(key(100+i),10000) for i in range(19)]}
    return pool,largest,batch


class PoolProof(unittest.TestCase):
    def test_base58_roundtrip_and_invalid_length(self):
        for raw in (b'\0'*32,bytes(range(32)),bytes([255])*32):self.assertEqual(v.key_bytes(v.b58encode(raw)),raw)
        for bad in ('A'*32,'O'*44,'',True):
            with self.assertRaises(ValueError):v.key_bytes(bad)
    def test_pump_pda_matches_published_official_example(self):
        pair=v.pda_with_stored_bump([b'pool',b'\0\0',v.key_bytes('9XDYTfQKwW8sHPqnFdUreMmtmffmkHVPGTNV2e3LKxNW'),v.key_bytes('7LSsEoJGhLeZzGvDofTdNg7M3JttxQqGWNLo6vWMpump'),v.key_bytes(QUOTE)],254,v.PUMP)
        self.assertEqual(pair,'GseMAnNDvntR5uFePZ51yZBXzNSn7GdFPkfHwfr6d77J')
    def test_four_protocols_and_both_mint_sides(self):
        for protocol in (v.PUMP,v.CPMM,v.CLMM,v.AMM_V4):
            for side in (False,True):
                p,a,t=pool_fixture(protocol,side);proof=v.pool_vault(p,a)
                self.assertEqual(proof['vault'],VAULT)
                self.assertEqual(v.verify_vault(proof,t,bot.PROGRAM)['amount'],800000)
    def test_customizable_clmm_seed_is_checked(self):
        p,a,t=pool_fixture(v.CLMM,custom_clmm=True)
        self.assertEqual(v.verify_vault(v.pool_vault(p,a),t,bot.PROGRAM)['amount'],800000)
        p['pairAddress']=key(9)
        with self.assertRaises(ValueError):v.pool_vault(p,a)
    def test_fake_pool_program_cannot_exempt_a_whale(self):
        p,a,_=pool_fixture();a['owner']=key(9)
        with self.assertRaises(ValueError):v.pool_vault(p,a)
    def test_wrong_discriminator_truncated_layout_and_pda_rejected(self):
        p,a,_=pool_fixture()
        for raw in (v.raw_data(a)[:80],b'\0'*8+v.raw_data(a)[8:]):
            with self.assertRaises(ValueError):v.pool_vault(p,account(raw,v.PUMP))
        p['pairAddress']=key(9)
        with self.assertRaises(ValueError):v.pool_vault(p,a)
    def test_metadata_vault_label_cannot_replace_onchain_address(self):
        p,a,_=pool_fixture();p['vaultAddress']=key(99);p['info']={'vaults':[key(99)]}
        self.assertEqual(v.pool_vault(p,a)['vault'],VAULT)
    def test_wrong_mint_or_quote_is_rejected(self):
        p,a,_=pool_fixture();p['quoteToken']['address']=key(9)
        with self.assertRaises(ValueError):v.pool_vault(p,a)
        p,a,_=pool_fixture();p['baseToken']['address']=key(9)
        with self.assertRaises(ValueError):v.pool_vault(p,a)
    def test_token_owner_mint_program_and_authority_must_match(self):
        p,a,t=pool_fixture();proof=v.pool_vault(p,a)
        for bad in (token(key(99),800000),token(proof['authority'],800000,mint=key(99)),token(proof['authority'],800000,token_program=key(99))):
            with self.assertRaises(ValueError):v.verify_vault(proof,bad,bot.PROGRAM)
    def test_frozen_delegated_and_foreign_close_authority_refused(self):
        p,a,t=pool_fixture();proof=v.pool_vault(p,a)
        for offset,value in ((108,b'\2'),(72,b'\1\0\0\0'),(129,b'\1\0\0\0')):
            raw=bytearray(v.raw_data(t));raw[offset:offset+len(value)]=value
            with self.assertRaises(ValueError):v.verify_vault(proof,account(raw,bot.PROGRAM),bot.PROGRAM)
    def test_token2022_only_immutable_owner_extension_is_exempted(self):
        p,a,t=pool_fixture();proof=v.pool_vault(p,a)
        good=token(proof['authority'],800000,token_program=bot.TOKEN_2022,extra=b'\2\7\0\0\0')
        self.assertEqual(v.verify_vault(proof,good,bot.TOKEN_2022)['amount'],800000)
        bad=token(proof['authority'],800000,token_program=bot.TOKEN_2022,extra=b'\2\x08\0\0\0')
        with self.assertRaises(ValueError):v.verify_vault(proof,bad,bot.TOKEN_2022)
    def test_paused_pool_is_identified(self):
        for program,offset,mask in ((v.CPMM,329,4),(v.CLMM,389,16)):
            p,a,_=pool_fixture(program);raw=bytearray(v.raw_data(a));raw[offset]|=mask
            self.assertTrue(v.pool_vault(p,account(raw,program))['swaps_disabled'])


class Concentration(unittest.TestCase):
    def check(self,p,largest,batch):
        with patch.object(evidence,'rpc',side_effect=[largest,batch]):return v.concentration(p,mint_account(),bot,evidence.rpc)
    def test_raw_89_percent_becomes_10_only_after_vault_proof(self):
        for program in (v.PUMP,v.CPMM,v.CLMM,v.AMM_V4):
            p,l,b=snapshots(program);result=self.check(p,l,b)
            self.assertTrue(result['verified']);self.assertEqual(result['raw_top10_pct'],89)
            self.assertEqual(result['top10_accounts_pct'],10);self.assertEqual(result['excluded_pct'],80)
            self.assertEqual(result['vault_status'],'onchain_verified')
    def test_fake_vault_still_counts_in_raw_concentration(self):
        p,l,b=snapshots();b['value'][2]=token(key(99),800000)
        r=self.check(p,l,b);self.assertEqual(r['top10_accounts_pct'],89);self.assertFalse(r['excluded_vaults'])
    def test_unknown_program_is_conservative(self):
        p,l,b=snapshots();b['value'][1]['owner']=key(99)
        r=self.check(p,l,b);self.assertEqual(r['top10_accounts_pct'],89);self.assertFalse(r['excluded_vaults'])
    def test_snapshot_failure_or_stale_slot_never_keeps_exemptions(self):
        for kind in ('failed','old','future','supply','missing'):
            p,l,b=snapshots()
            if kind=='failed': b=TimeoutError()
            elif kind=='old':b['context']['slot']=999
            elif kind=='future':b['context']['slot']=1041
            elif kind=='supply':b['value'][0]=mint_account(999999)
            else:b['value'][3]=None
            r=self.check(p,l,b);self.assertFalse(r['verified']);self.assertEqual(r['top10_accounts_pct'],89);self.assertFalse(r['excluded_vaults'])
    def test_trades_between_queries_do_not_invalidate_vault_identity(self):
        p,l,b=snapshots();b['value'][2]=token(p['pairAddress'],799999)
        r=self.check(p,l,b)
        self.assertTrue(r['verified']);self.assertTrue(r['balances_changed_during_proof'])
        self.assertEqual(r['top10_accounts_pct'],10);self.assertEqual(r['excluded_pct'],80)
        self.assertEqual(r['context_slot'],1000);self.assertEqual(r['proof_context_slot'],1001)
    def test_duplicate_or_unsorted_accounts_are_rejected(self):
        p,l,b=snapshots();l['value'][1]['address']=VAULT
        with self.assertRaises(ValueError):self.check(p,l,b)
        p,l,b=snapshots();l['value'].reverse()
        with self.assertRaises(ValueError):self.check(p,l,b)
    def test_shared_wallet_is_aggregated_across_token_accounts(self):
        p,l,b=snapshots();b['value'][3:]=[token(key(99),10000) for _ in range(19)]
        r=self.check(p,l,b);self.assertEqual(r['top10_accounts_pct'],10);self.assertEqual(r['top1_observed_owner_pct'],19)
    def test_security_retains_other_gates_after_correction(self):
        p,l,b=snapshots()
        with patch.object(evidence,'rpc',side_effect=[{'value':mint_account()},l,b]),patch.object(bot,'request',return_value={'score_normalised':0,'risks':[]}):
            result=evidence.security(MINT,bot,NOW,pool=p)
        self.assertIsNone(result['reject']);self.assertTrue(result['complete']);self.assertEqual(result['score'],100)
    def test_verified_vault_never_bypasses_rugcheck_danger(self):
        p,l,b=snapshots()
        with patch.object(evidence,'rpc',side_effect=[{'value':mint_account()},l,b]),patch.object(bot,'request',return_value={'score_normalised':0,'risks':[{'level':'danger'}]}):
            self.assertEqual(evidence.security(MINT,bot,NOW,pool=p)['reject'],'danger_risk_flag')
    def test_active_mint_authority_stops_before_vault_exemption(self):
        p,_,_=snapshots();a=mint_account();raw=bytearray(v.raw_data(a));struct.pack_into('<I',raw,0,1)
        with patch.object(evidence,'rpc',return_value={'value':account(raw,bot.PROGRAM)}) as rpc:
            self.assertEqual(evidence.security(MINT,bot,NOW,pool=p)['reject'],'mint_authority_active')
        self.assertEqual(rpc.call_count,1)
    def test_security_rejects_real_concentration_and_paused_pools(self):
        for reason in ('vault_fake','one_owner','paused'):
            p,l,b=snapshots(v.CPMM)
            if reason=='vault_fake':b['value'][2]=token(key(99),800000)
            elif reason=='one_owner':b['value'][3:]=[token(key(99),10000) for _ in range(19)]
            else:
                raw=bytearray(v.raw_data(b['value'][1]));raw[329]=4;b['value'][1]=account(raw,v.CPMM)
            with patch.object(evidence,'rpc',side_effect=[{'value':mint_account()},l,b]):r=evidence.security(MINT,bot,NOW,pool=p)
            self.assertEqual(r['reject'],{'vault_fake':'top10_accounts_over_30','one_owner':'observed_owner_over_15','paused':'pool_swaps_disabled'}[reason])
    def test_alert_labels_corrected_and_uncorrected_numbers(self):
        p,l,b=snapshots();s=sec();s['distribution']=self.check(p,l,b);s['top10_accounts_pct']=10
        marketp=market_pool();m=market(marketp,{},NOW)
        text=scanner_v2.render(marketp,m,s,social(),{'unique_buyers':25,'strong':True},mint_age(),'EARLY WATCH')
        self.assertIn('Sebelum koreksi 89.00%',text);self.assertIn('10.00%',text);self.assertIn('vault LP terbukti',text)
    def test_schedule_history_is_durable_bounded_and_deduplicated(self):
        event={'at':NOW,'trigger':'schedule','run_id':'123','seen':10,'sent':0}
        merged=state_store.merge({'scan_history':[event]},{'scan_history':[event]},NOW)
        self.assertEqual(merged['scan_history'],[event])
        merged['scan_history'] += [dict(event,at=NOW-8*86400)]
        self.assertEqual(state_store.migrate(merged,NOW)['scan_history'],[event])


if __name__=='__main__':unittest.main()
