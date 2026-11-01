"""Small operational smoke checks for the new shell; does not repeat old audits.

Fixtures are synthetic and are never reported as a live market BUY/SELL cycle.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import patch

from sniper_cloud_worker import Control, Worker, guarded_bot, http_server, enforce_paper
from solana_sniper_paper import candidate


def main():
    checks = []
    with tempfile.TemporaryDirectory() as directory:
        control = Control(directory)
        token = 'operational-fixture-token-only-123456789'
        server = http_server(control, token, 0, lambda: True, host='127.0.0.1')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port)
        def request(path, method='GET', authorized=True):
            headers = {'Authorization': 'Bearer ' + token} if authorized else {}
            with urllib.request.urlopen(urllib.request.Request(url+path, method=method, headers=headers), timeout=5) as response:
                return response.status, json.load(response)
        try:
            try:
                request('/api/on', 'POST', authorized=False)
                raise AssertionError('Unauthorized ON accepted')
            except urllib.error.HTTPError as error:
                assert error.code == 401
            assert not control.entries_allowed()
            checks.append('HTTP unauthorized ON denied; initial OFF')
            assert request('/healthz', authorized=False)[0] == 200
            request('/api/on', 'POST')
            deadline = control.state()['deadline']
            assert control.entries_allowed()
            bot = guarded_bot(control, threading.Event())(control.database)
            for mint in ('CLOUD_FIXTURE_A', 'CLOUD_FIXTURE_B'):
                assert bot.process(candidate(mint, pair_address='PAIR_'+mint))['action'] == 'PAPER_BUY'
            assert bot.process(candidate('CLOUD_FIXTURE_C', pair_address='PAIR_C'))['action'] == 'REJECT'
            assert len(bot.positions) == 2
            checks.append('Authenticated ON; existing $5 engine enforces two positions')
            request('/api/off', 'POST')
            assert bot.process(candidate('CLOUD_FIXTURE_D', pair_address='PAIR_D'))['action'] == 'PAPER_PAUSED'
            a = bot.process(dict(type='price', mint='CLOUD_FIXTURE_A', price=1.3, now=1001, observed_at=1001))
            assert a['action'] == 'PAPER_SELL' and a['trigger'] == 'TP'
            bot.close()
            control = Control(directory, initial_on=True)
            assert not control.entries_allowed() and control.state()['deadline'] == deadline
            bot = guarded_bot(control, threading.Event())(control.database)
            assert list(bot.positions) == ['CLOUD_FIXTURE_B']
            b = bot.process(dict(type='price', mint='CLOUD_FIXTURE_B', price=.8, now=1002, observed_at=1002))
            assert b['action'] == 'PAPER_SELL' and b['trigger'] == 'SL'
            checks.append('OFF rejects entry; restart preserves OFF, deadline, pinned position; TP/SL exits still work')
            assert abs(b['net_pnl_usd'] - ((5/1.005)*.8*.995*.987-.05-5.115)) < .000001
            control.switch(True)
            assert 'duplicate_mint' in bot.process(candidate('CLOUD_FIXTURE_A', pair_address='PAIR_A', now=1003, observed_at=1003))['reasons']
            bot.close()
            checks.append('Restart dedup retained; exit PnL includes existing fees/slippage')
            with control.connect() as db:
                db.execute('UPDATE cloud_control SET deadline=? WHERE id=1', (time.time()-1,))
            assert not control.entries_allowed()
            try:
                control.switch(True)
                raise AssertionError('Expired session reactivated')
            except ValueError:
                pass
            checks.append('24h deadline cannot silently reset or reactivate after restart')
            control.switch(False)
            Worker(control, interval=0).run(max_rounds=1)
            report = request('/api/report')[1]
            assert report['rounds'] == 1 and report['recent_rounds'][0]['request_count'] == 0
            assert report['durable_state']['positions'] == {}
            assert report['event_counts']['PAPER_BUY'] == 2 and report['event_counts']['PAPER_SELL'] == 2
            assert not report['continuous_24h_proven'] and not report['real_trading']
            checks.append('Existing discovery pipeline runs OFF with zero network requests; authenticated report records round/run')
            with patch.dict(os.environ, {'REAL_TRADING':'ON'}):
                try:
                    enforce_paper()
                    raise AssertionError('REAL enabled')
                except ValueError:
                    pass
            checks.append('REAL ON refuses startup')
            result = dict(result='PASS', operational_checks=len(checks), checks=checks,
                          fixture_only=True, real_market_cycle_proven=False,
                          synthetic_tp=a, synthetic_sl=b)
            Path('sniper_cloud_operational_checks.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
