"""Bounded local operational run with real read-only APIs; not a cloud uptime claim."""
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main():
    root = Path(__file__).resolve().parent
    # Keep an actively written WAL database on one native filesystem for this
    # subprocess check, outside workspace transfer/snapshot boundaries.
    directory = Path(tempfile.mkdtemp(prefix='sniper-cloud-operational-'))
    token = secrets.token_urlsafe(32)
    env = dict(os.environ, SNIPER_CONTROL_TOKEN=token, PAPER_ONLY='1', REAL_TRADING='OFF',
               SNIPER_INITIAL_ON='1', SOLANA_READONLY_RPC='https://solana-rpc.publicnode.com')
    result = dict(scope='LOCAL_OPERATIONAL_CHECK_NOT_CLOUD', started=time.time(),
                  mode='PAPER_ONLY_REAL_OFF', continuous_24h_proven=False)
    from sniper_cloud_worker import Control
    prior = Control(directory, seed=str(root/'sniper_paper.sqlite3'))
    baseline_rounds = prior.report()['rounds']
    prior.switch(True)
    base = 'http://127.0.0.1:18764'
    def call(path, method='GET'):
        req = urllib.request.Request(base+path, method=method,
                                     headers={'Authorization':'Bearer '+token})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)
    with (root / 'sniper_cloud_live_process.log').open('w') as log:
        process = subprocess.Popen(['python3', '-u', str(root/'sniper_cloud_worker.py'),
            '--data-dir', str(directory), '--seed-db', str(root/'sniper_paper.sqlite3'),
            '--port', '18764', '--max-rounds', '2', '--interval', '15'], env=env, stdout=log, stderr=log)
        try:
            ready = False
            off = False
            while process.poll() is None and time.time()-result['started'] < 300:
                try:
                    health = call('/healthz')
                    if not ready:
                        result['health'] = health
                        result['on'] = call('/api/on', 'POST')
                        ready = True
                        print('HTTP health/authenticated ON ready; real API round running', flush=True)
                    report = call('/api/report')
                    if (report['rounds'] > baseline_rounds or time.time()-result['started'] >= 30) and not off:
                        result['off'] = call('/api/off', 'POST')
                        off = True
                        print('Authenticated OFF confirmed; cancelling entry discovery while preserving position monitoring', flush=True)
                except (urllib.error.URLError, TimeoutError):
                    pass
                time.sleep(2)
            if process.poll() is None:
                result['bounded_timeout'] = True
                try:
                    result['off'] = call('/api/off', 'POST')
                except Exception:
                    pass
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill()
                    result['shutdown_kill_required'] = True
            process.wait(timeout=10)
            result['exit_code'] = process.returncode
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    control = Control(directory)
    result['final_report'] = control.report()
    with control.connect() as db:
        result['database_integrity'] = db.execute('PRAGMA integrity_check').fetchone()[0]
    # A real process restart, in OFF state, uses the very same test database.
    before = control.report()['durable_state']
    with (root / 'sniper_cloud_restart_process.log').open('w') as restart_log:
        restarted = subprocess.Popen(['python3', '-u', str(root/'sniper_cloud_worker.py'),
            '--data-dir', str(directory), '--port', '18764', '--max-rounds', '1'],
            env=env, stdout=restart_log, stderr=restart_log)
        try:
            result['restart_exit_code'] = restarted.wait(timeout=20)
        except subprocess.TimeoutExpired:
            restarted.kill();restarted.wait();result['restart_exit_code'] = -9
    result['restart_state_equal'] = Control(directory).report()['durable_state'] == before
    with control.connect() as db:
        result['database_integrity_after_restart'] = db.execute('PRAGMA integrity_check').fetchone()[0]
    result['finished'] = time.time()
    result['result'] = ('PASS' if result.get('health', {}).get('worker_alive')
                        and result.get('off', {}).get('enabled') is False
                        and result.get('exit_code') == 0
                        and result['final_report']['rounds']-baseline_rounds >= 2
                        and result['database_integrity'] == 'ok'
                        and result['database_integrity_after_restart'] == 'ok'
                        and result['restart_exit_code'] == 0 and result['restart_state_equal']
                        and not result.get('bounded_timeout') else 'INCOMPLETE')
    (root/'sniper_cloud_live_operational.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='final_report'}), flush=True)


if __name__ == '__main__':
    main()
