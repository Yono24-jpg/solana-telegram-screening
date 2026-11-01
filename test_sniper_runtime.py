"""Regression, restart/crash, concurrency, discovery and on-chain evidence tests."""
import concurrent.futures
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from solana_sniper_paper import candidate
from solana_market_readonly import Reader, TOKEN_PROGRAM, TOKEN_2022, transaction_proof, initialized_mints, run
from sniper_runtime import PersistentPaperBot, RateLimiter


def entry(mint='M',**values):
    return candidate(mint,pair_address='PAIR_'+mint,**values)


def tx(mint='M',signature='SIG',program=TOKEN_PROGRAM):
    return dict(slot=10,blockTime=900,meta=dict(err=None),transaction=dict(signatures=[signature],message=dict(
        instructions=[dict(programId=program,parsed=dict(type='initializeMint2',info=dict(mint=mint)))])))


class FakeClock:
    def __init__(self): self.now=0; self.waits=[]
    def time(self): return self.now
    def sleep(self,duration): self.waits.append(duration); self.now+=duration


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=str(Path(self.folder.name)/'state.sqlite3')

    def tearDown(self): self.folder.cleanup()

    def test_restart_no_duplicate_and_pair_pin_recovery(self):
        bot=PersistentPaperBot(self.path)
        self.assertEqual(bot.process(entry())['action'],'PAPER_BUY')
        before=bot.snapshot();bot.close()
        restored=PersistentPaperBot(self.path)
        self.assertEqual(restored.snapshot(),before)
        self.assertEqual(restored.pins['M'],'PAIR_M')
        self.assertIn('duplicate_mint',restored.process(entry())['reasons'])
        self.assertEqual(len(restored.positions),1)
        restored.close()

    def test_sell_after_restart_and_never_reenter_closed_mint(self):
        bot=PersistentPaperBot(self.path);bot.process(entry());bot.close()
        bot=PersistentPaperBot(self.path)
        sell=bot.process(dict(type='price',mint='M',price=1.21,now=1001,observed_at=1001))
        self.assertEqual(sell['trigger'],'TP')
        profit=bot.pnl;bot.close()
        bot=PersistentPaperBot(self.path)
        self.assertEqual(bot.pnl,profit);self.assertEqual(bot.positions,{})
        self.assertIn('duplicate_mint',bot.process(entry(now=1002,observed_at=1002))['reasons'])
        bot.close()

    def test_stop_loss_after_restart_includes_fees_and_gap(self):
        bot=PersistentPaperBot(self.path);bot.process(entry());bot.close()
        bot=PersistentPaperBot(self.path)
        sell=bot.process(dict(type='price',mint='M',price=.8,now=1001,observed_at=1001))
        self.assertEqual(sell['trigger'],'SL')
        self.assertAlmostEqual(sell['net_pnl_usd'],(5/1.005)*.8*.995*.987-.05-5.115,places=6)
        self.assertEqual(bot.positions,{})
        bot.close()

    def test_concurrent_instances_share_two_slots(self):
        PersistentPaperBot(self.path).close()
        def enter(i):
            bot=PersistentPaperBot(self.path)
            try:return bot.process(entry(str(i)))['action']
            finally:bot.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            actions=list(pool.map(enter,range(12)))
        self.assertEqual(actions.count('PAPER_BUY'),2)
        bot=PersistentPaperBot(self.path);self.assertEqual(len(bot.positions),2);bot.close()

    def test_concurrent_duplicate_is_one_buy(self):
        PersistentPaperBot(self.path).close()
        def enter(_):
            bot=PersistentPaperBot(self.path)
            try:return bot.process(entry())['action']
            finally:bot.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            actions=list(pool.map(enter,range(6)))
        self.assertEqual(actions.count('PAPER_BUY'),1)

    def test_hard_crash_before_commit_rolls_back_whole_decision(self):
        PersistentPaperBot(self.path).close()
        script="""import os,sys
from sniper_runtime import PersistentPaperBot
from solana_sniper_paper import candidate
b=PersistentPaperBot(sys.argv[1]); save=b._save
def crash():
 save(); os._exit(9)
b._save=crash
b.process(candidate('M',pair_address='PAIR_M'))
"""
        result=subprocess.run([sys.executable,'-c',script,self.path],capture_output=True)
        self.assertEqual(result.returncode,9)
        bot=PersistentPaperBot(self.path);self.assertEqual(bot.positions,{})
        self.assertNotIn('M',bot.seen)
        self.assertEqual(bot.process(entry())['action'],'PAPER_BUY');bot.close()

    def test_hard_crash_after_commit_recovers_buy_without_duplicate(self):
        script="""import os,sys
from sniper_runtime import PersistentPaperBot
from solana_sniper_paper import candidate
b=PersistentPaperBot(sys.argv[1]);b.process(candidate('M',pair_address='PAIR_M'));os._exit(9)
"""
        self.assertEqual(subprocess.run([sys.executable,'-c',script,self.path],capture_output=True).returncode,9)
        bot=PersistentPaperBot(self.path)
        self.assertEqual(len(bot.positions),1)
        self.assertIn('duplicate_mint',bot.process(entry())['reasons']);bot.close()

    def test_state_config_or_corruption_fails_closed(self):
        bot=PersistentPaperBot(self.path);bot.process(entry());bot.close()
        with self.assertRaises(ValueError):PersistentPaperBot(self.path,fixed=.01)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE state SET payload='not-json'")
        with self.assertRaises(ValueError):PersistentPaperBot(self.path)

    def test_missing_pair_stale_data_unknown_security_reject(self):
        bot=PersistentPaperBot(self.path)
        self.assertEqual(bot.process(candidate())['action'],'REJECT')
        self.assertEqual(bot.process(entry(observed_at=960))['action'],'REJECT')
        self.assertEqual(bot.process(entry(mint_revoked=None))['action'],'REJECT')
        self.assertEqual(bot.positions,{})
        bot.close()

    def test_finalized_proof_exact_signature_program_slot_and_success(self):
        self.assertTrue(transaction_proof(tx(),'M','SIG'))
        self.assertIsNone(transaction_proof(tx(),'OTHER','SIG'))
        self.assertIsNone(transaction_proof(tx(),'M','WRONG_SIG'))
        self.assertIsNone(transaction_proof(tx(program=TOKEN_2022),'M','SIG'))
        for field in ('blockTime','slot'):
            data=tx();data[field]=None
            self.assertIsNone(transaction_proof(data,'M','SIG'))
        data=tx();data['meta']={}
        self.assertIsNone(transaction_proof(data,'M','SIG'))
        data=tx();data['meta']['err']='failed'
        self.assertEqual(initialized_mints(data),[])

    def test_oldest_signature_is_not_birth(self):
        bot=PersistentPaperBot(self.path);reader=Reader(bot)
        data=tx();data['transaction']['message']['instructions']=[]
        with patch.object(reader,'rpc',side_effect=[
            [dict(signature='SIG',slot=10,err=None)],data]):
            self.assertIsNone(reader.mint_birth('M'))
        self.assertIsNone(bot.cache_get('birth','M'));bot.close()

    def test_birth_proof_saved_and_reused_after_restart(self):
        bot=PersistentPaperBot(self.path);reader=Reader(bot)
        with patch.object(reader,'rpc',side_effect=[
            [dict(signature='SIG',slot=10,err=None)],tx()]):
            self.assertTrue(reader.mint_birth('M'))
        bot.close();bot=PersistentPaperBot(self.path);reader=Reader(bot)
        with patch.object(reader,'rpc') as rpc:
            self.assertEqual(reader.mint_birth('M')['signature'],'SIG')
            rpc.assert_not_called()
        bot.close()

    def test_pagination_cursor_survives_restart(self):
        bot=PersistentPaperBot(self.path);reader=Reader(bot)
        pages=[[dict(signature=f'{p}_{i}',slot=10000-p*1000-i,err='failed') for i in range(1000)] for p in range(2)]
        with patch.object(reader,'rpc',side_effect=pages):self.assertIsNone(reader.mint_birth('M'))
        self.assertEqual(bot.cache_get('birth_scan','M')['before'],'1_999')
        bot.close();bot=PersistentPaperBot(self.path);reader=Reader(bot)
        with patch.object(reader,'rpc',return_value=[]) as rpc:
            self.assertIsNone(reader.mint_birth('M'))
            self.assertEqual(rpc.call_args.args[1][1]['before'],'1_999')
        bot.close()

    def test_rate_limits_spacing_window_and_long_cooldown(self):
        fake=FakeClock();rate=RateLimiter(2,window=60,spacing=3,clock=fake.time,sleep=fake.sleep)
        rate.wait();rate.wait();rate.wait()
        self.assertEqual(fake.waits,[3,57])
        rate.cooldown(120)
        with self.assertRaises(RuntimeError):rate.wait()

    def test_429_retry_after_is_respected_and_attempts_audited(self):
        fake=FakeClock();reader=Reader()
        reader.limits['MARKET_GET']=RateLimiter(30,spacing=2,clock=fake.time,sleep=fake.sleep)
        response=io.BytesIO(b'[]');response.headers={}
        error=urllib.error.HTTPError('https://api.dexscreener.com',429,'limited',{'Retry-After':'10'},None)
        with patch('urllib.request.urlopen',side_effect=[error,response]):
            self.assertEqual(reader.market('/token-profiles/latest/v1'),[])
        self.assertEqual(fake.waits,[10]);self.assertEqual([r['status'] for r in reader.requests],[429,'ok'])

    def test_request_layer_also_blocks_send(self):
        with self.assertRaises(ValueError):Reader().request('https://example.invalid',{'method':'sendTransaction'})

    def test_discovery_union_and_batches_are_not_capped_at_30(self):
        bot=PersistentPaperBot(self.path);reader=Reader(bot);calls=[]
        def market(path):
            calls.append(path)
            if path.startswith('/tokens/'):
                self.assertLessEqual(len(path.rsplit('/',1)[1].split(',')),30)
                return []
            return [dict(chainId='solana',tokenAddress=f'{len(calls):02d}{i:030d}') for i in range(35)]
        with patch.object(reader,'market',side_effect=market),patch.object(reader,'recent_tokens',return_value=[]),patch.object(reader,'new_pools',return_value={'data':[]}):
            mints,_,audit=reader.discover(0,max_tokens=120,onchain_transactions=0)
        self.assertEqual(len(mints),120)
        self.assertEqual(sum(p.startswith('/tokens/') for p in calls),4)
        self.assertGreater(audit['watchlist_eligible'],30)
        bot.close()

    def test_full_adapter_buy_monitor_tp_sl_and_restart(self):
        # Explicit SYNTHETIC fixtures: validates orchestration, not live trading results.
        now=time.time()
        def pair(mint,price=1):
            return dict(chainId='solana',pairAddress='PAIR_'+mint,baseToken=dict(address=mint,symbol=mint),
                priceUsd=str(price),pairCreatedAt=(now-600)*1000,liquidity=dict(usd=12000),
                volume=dict(m5=1800),txns=dict(m5=dict(buys=18,sells=12)))
        fake=Reader();counts={}
        fake.discover=lambda round_id,*args: (['A','B','C'],[pair(m) for m in ('A','B','C')],{}) if round_id==0 else ([],[],{})
        fake.security=lambda mint:dict(verified=True,authority_data_verified=True,mint_revoked=True,
                                       freeze_revoked=True,raw=dict(owner=TOKEN_2022 if mint=='B' else TOKEN_PROGRAM),extension_audit=dict(verified=True),observed_at=time.time())
        fake.exit_route=lambda mint,quantity:dict(verified=True,observed_at=time.time())
        fake.sell_route=lambda mint:dict(verified=True,observed_at=time.time())
        fake.mint_birth=lambda mint,**kwargs:dict(block_time=now-600)
        def market(path):
            mint=path[-1];counts[mint]=counts.get(mint,0)+1
            return dict(pairs=[pair(mint,1 if counts[mint]==1 else 1.21 if mint=='A' else .89)])
        fake.market=market
        args=SimpleNamespace(state_db=self.path,rounds=2,interval=5,max_tokens=120,onchain_transactions=0,
                             max_security=3,output=str(Path(self.folder.name)/'evidence.json'))
        with patch('solana_market_readonly.Reader',return_value=fake),patch('time.sleep'),patch('builtins.print'):
            result=run(args)
        self.assertEqual(result['summary']['actions']['PAPER_BUY'],2)
        self.assertEqual(result['summary']['max_positions_observed'],2)
        self.assertEqual(result['summary']['unique_mints_checked'],3)
        self.assertEqual(result['summary']['repeated_checks'],0)
        self.assertEqual(result['summary']['market_pass_checks'],3)
        self.assertEqual(result['summary']['security_pass_unique_by_program'],{TOKEN_PROGRAM:2,TOKEN_2022:1})
        self.assertEqual(result['summary']['complete_verification_attempts'],3)
        self.assertEqual(result['summary']['stage_unique_mints']['mint_age']['pass'],3)
        self.assertEqual([x['outcome']['trigger'] for x in result['rounds'][1]['marks']],['TP','SL'])
        self.assertEqual(result['summary']['open_positions'],{})
        restored=PersistentPaperBot(self.path)
        self.assertEqual(restored.seen,{'A','B'})
        stamp=time.time()
        self.assertIn('duplicate_mint',restored.process(entry('A',now=stamp,observed_at=stamp))['reasons'])
        restored.close()


if __name__ == '__main__':unittest.main(verbosity=2)
