"""Pipeline and durable-state tests; all external services are mocked."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import bot
import evidence
import persist_state
import scanner_v2
import state_store
from test_upgrade import pool, history, sec, social, mint_age, NOW, MINT


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.api = bot
        self.old_deadline = bot.REQUEST_DEADLINE
        bot.REQUEST_DEADLINE = None
    def tearDown(self):bot.REQUEST_DEADLINE=self.old_deadline
    def run_scan(self,state,security=None,community=None,creation=None,buyers=None):
        with patch.object(scanner_v2,'discover',return_value=([pool()],{'sources':{}})),patch.object(bot,'refresh_watchlist',side_effect=lambda pools,*_:pools),patch.object(scanner_v2,'checkpoint'),patch.object(scanner_v2,'followup'),patch.object(scanner_v2.time,'time',return_value=NOW),patch.object(evidence,'security',return_value=security or sec()),patch.object(evidence,'community',return_value=community or social()),patch.object(evidence,'mint_creation',return_value=creation or mint_age()),patch.object(evidence,'buyers',return_value=buyers or {'strong':True,'unique_buyers':25}),patch.object(scanner_v2,'refresh',return_value=pool()),patch.object(scanner_v2.Path,'mkdir'),patch.object(scanner_v2.Path,'write_text'),patch.object(bot,'tg',return_value={'message_id':99,'chat':{'id':123}}) as tg:
            scanner_v2.run(state,123,bot)
            return tg
    def test_full_pipeline_strong_and_restart_dedup(self):
        state={'enabled':True,'sent':{},'observations':history()}
        tg=self.run_scan(state)
        self.assertEqual(tg.call_count,1)
        self.assertIn('STRONG SIGNAL',tg.call_args.kwargs['text'])
        restored=json.loads(json.dumps(state))
        self.assertEqual(self.run_scan(restored).call_count,0)
    def test_missing_social_data_only_watch_and_once(self):
        state={'enabled':True,'observations':history()}
        unknown=social();unknown.update(complete=False,score=None)
        tg=self.run_scan(state,community=unknown)
        self.assertIn('EARLY WATCH',tg.call_args.kwargs['text'])
        self.assertIn('belum cukup data',tg.call_args.kwargs['text'])
        self.assertEqual(self.run_scan(state,community=unknown).call_count,0)
    def test_security_failure_blocks_all_notifications(self):
        state={'enabled':True,'observations':history()};s=sec();s['reject']='mint_authority_active'
        self.assertEqual(self.run_scan(state,security=s).call_count,0)
    def test_manager_off_restored_before_delivery_stops_send(self):
        state=state_store.migrate({'enabled':True},NOW)
        def off(*_args,**_kwargs):state['enabled']=False
        with patch.object(scanner_v2,'checkpoint',side_effect=off),patch.object(bot,'tg') as tg:
            self.assertFalse(scanner_v2.deliver(state,bot,123,pool(),{},sec(),social(),{},mint_age(),'EARLY WATCH'))
        tg.assert_not_called()
    def test_observations_include_24h_pools_and_exclude_older(self):
        state={};scanner_v2.observe(state,[pool(86400)],NOW)
        self.assertTrue(state['observations'])
        state={};scanner_v2.observe(state,[pool(86401)],NOW)
        self.assertEqual(state['observations'],{})
    def test_discovery_keeps_both_feeds_and_metadata(self):
        def request(url,*args):
            if 'new_pools' in url:return {'data':[{'attributes':{'address':pool()['pairAddress']}}]}
            if '/tokens/v1/' in url:return [pool()]
            if '/latest/dex/pairs/' in url:return {'pairs':[pool()]}
            return [{'chainId':'solana','tokenAddress':MINT,'links':[{'url':'https://x.com/validuser'}]}]
        with patch.object(bot,'request',side_effect=request):
            rows,report=scanner_v2.discover(bot)
        self.assertEqual(report['new_pool_addresses'],1);self.assertEqual(report['token_addresses'],1)
        self.assertEqual(len(rows),1);self.assertIn('socials',rows[0]['info'])


class Persistence(unittest.TestCase):
    def test_commit_changes_only_state_and_merges_remote_control(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*args,cwd=None):
                return subprocess.check_output(['git',*args],cwd=cwd or d,stderr=subprocess.DEVNULL,text=True).strip()
            git('init','--bare',d+'/remote.git')
            git('clone',d+'/remote.git',d+'/work')
            work=d+'/work'
            git('config','user.name','Test',cwd=work);git('config','user.email','test@example.invalid',cwd=work)
            git('checkout','-b','main',cwd=work)
            Path(work+'/state.json').write_text(json.dumps({'enabled':False,'offset':10,'sent':{}}))
            Path(work+'/keep.py').write_text('original\n')
            git('add','.',cwd=work);git('commit','-m','base',cwd=work);git('push','origin','main',cwd=work)
            # Uncommitted source edits must survive persistence and never be included in state commits.
            Path(work+'/keep.py').write_text('local changes\n')
            local={'enabled':True,'offset':9,'delivery':{'key':{'at':NOW,'reservation':'a','status':'pending'}}}
            Path(work+'/state.json').write_text(json.dumps(local))
            previous=os.getcwd()
            try:
                os.chdir(work)
                with patch.object(persist_state.time,'time',return_value=NOW): merged=persist_state.persist()
            finally:os.chdir(previous)
            self.assertFalse(merged['enabled']);self.assertEqual(merged['offset'],10)
            self.assertEqual(git('show','origin/main:keep.py',cwd=work),'original')
            self.assertEqual(Path(work+'/keep.py').read_text(),'local changes\n')
            self.assertIn('key',json.loads(git('show','origin/main:state.json',cwd=work))['delivery'])


if __name__=='__main__':unittest.main()
