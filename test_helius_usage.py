import os
import unittest
from unittest.mock import patch
import test_data_intelligence as fixtures
from test_upgrade import NOW,MINT
import data_intelligence as di
import state_store


class HeliusUsage(unittest.TestCase):
    def test_rolling_budget_survives_inactivity_and_prevents_network_call(self):
        day=int(NOW//86400)
        state={'provider_state_v5':{'helius':{'at':NOW-3*86400,'day':day-3,'requests':1,'credit_days':{str(day-3):600000}}}}
        state_store.migrate(state,NOW);api=fixtures.Providers().api()
        with patch.dict(os.environ,{'HELIUS_API_KEY':'test','SOLANA_RPC_URL':''}),patch.object(di.time,'time',return_value=NOW):
            client=di.Client(api,state)
            with self.assertRaisesRegex(di.Unavailable,'local_credit_budget'):
                client.request('helius','https://mainnet.helius-rpc.com/',{'method':'getSlot'})
        api.request.assert_not_called()
    def test_finalized_transaction_cache_is_defensive_and_never_caches_missing(self):
        api=fixtures.Providers().api();api.request.return_value={'result':{'slot':123,'meta':{'err':None}}}
        params=['signature',{'commitment':'finalized','encoding':'jsonParsed'}]
        with patch.dict(os.environ,{'HELIUS_API_KEY':'test','SOLANA_RPC_URL':''}),patch.object(di.time,'sleep'):
            client=di.Client(api,{})
            first=client.rpc('getTransaction',params);first['slot']=0
            self.assertEqual(client.rpc('getTransaction',params)['slot'],123)
            self.assertEqual(api.request.call_count,1)
            self.assertEqual(client.usage()['successful_rpc_by_method']['cache_hits'],1)
            self.assertEqual(client.usage()['helius_attempts_this_cycle'],1)
    def test_day_rollover_keeps_31_day_ledger_and_expires_old_days(self):
        day=int(NOW//86400);state={'provider_state_v5':{'helius':{'day':day-1,'requests':2,'at':NOW,'credit_days':{str(day-31):999,str(day-1):2}}}}
        api=fixtures.Providers().api();api.request.return_value={'result':123}
        with patch.dict(os.environ,{'HELIUS_API_KEY':'test','SOLANA_RPC_URL':''}),patch.object(di.time,'time',return_value=NOW):
            client=di.Client(api,state);client.rpc('getSlot',[])
        self.assertEqual(client.usage()['helius_estimated_credits_31d'],3)
        self.assertEqual(client.usage()['helius_estimated_credits_today'],1)

