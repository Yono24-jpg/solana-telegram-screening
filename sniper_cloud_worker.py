"""Operational shell for the existing validated engine. PAPER ONLY, no wallet API.

One process, one durable disk. OFF pauses discovery/entries, not position exits.
The first ON starts a durable 24h entry window. Expiry never forces a SELL.
"""
import argparse
import contextlib
import fcntl
import gzip
import hmac
import json
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import solana_market_readonly as engine
from sniper_runtime import PersistentPaperBot

MODE = 'PAPER_ONLY_REAL_OFF'


def enforce_paper():
    if os.environ.get('REAL_TRADING', 'OFF').upper() != 'OFF':
        raise ValueError('REAL_TRADING must be OFF')
    if os.environ.get('PAPER_ONLY', '1') != '1':
        raise ValueError('PAPER_ONLY must be 1')


@contextlib.contextmanager
def entry_lock(directory):
    with open(Path(directory) / 'entry.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


class Control:
    def __init__(self, directory, seed=None, initial_on=False):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / 'sniper_paper.sqlite3'
        # Initial seed is used once; a surviving database is never overwritten.
        if not self.database.exists() and seed:
            if Path(seed).suffix == '.json':
                state = json.loads(Path(seed).read_text())
                seeded = PersistentPaperBot(str(self.database) + '.seed')
                try:
                    seeded._load(state)  # Reuse the existing strict state validator.
                    seeded.db.execute('BEGIN IMMEDIATE')
                    seeded._save()
                    seeded.db.commit()
                    seeded.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                finally:
                    seeded.close()
            else:
                source = sqlite3.connect('file:' + str(Path(seed).resolve()) + '?mode=ro', uri=True)
                target = sqlite3.connect(str(self.database) + '.seed')
                try:
                    source.backup(target)
                    if target.execute('pragma integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Seed database integrity failed')
                finally:
                    target.close()
                    source.close()
            Path(str(self.database) + '.seed').replace(self.database)
        bot = PersistentPaperBot(self.database)
        bot.close()
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS cloud_control (
                id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
                session_started REAL, deadline REAL, updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS cloud_runs (
                id INTEGER PRIMARY KEY, started REAL NOT NULL, stopped REAL,
                heartbeat REAL NOT NULL, pid INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS cloud_rounds (
                id INTEGER PRIMARY KEY, finished REAL NOT NULL, payload TEXT NOT NULL);
            ''')
            now = time.time()
            db.execute('INSERT OR IGNORE INTO cloud_control VALUES(1,?,?,?,?)',
                       (int(initial_on), now if initial_on else None,
                        now + 86400 if initial_on else None, now))

    def connect(self):
        return contextlib.closing(sqlite3.connect(self.database, timeout=10, isolation_level=None))

    def state(self):
        with self.connect() as db:
            row = db.execute('SELECT enabled, session_started, deadline, updated FROM cloud_control WHERE id=1').fetchone()
        return dict(enabled=bool(row[0]), session_started=row[1], deadline=row[2], updated=row[3])

    def entries_allowed(self):
        state = self.state()
        return state['enabled'] and state['deadline'] is not None and time.time() < state['deadline']

    def switch(self, enabled):
        with entry_lock(self.directory), self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                start, deadline = db.execute('SELECT session_started,deadline FROM cloud_control WHERE id=1').fetchone()
                now = time.time()
                if enabled and deadline is not None and now >= deadline:
                    raise ValueError('24h entry window ended; no automatic reset')
                if enabled and start is None:
                    start, deadline = now, now + 86400
                db.execute('UPDATE cloud_control SET enabled=?,session_started=?,deadline=?,updated=? WHERE id=1',
                           (int(enabled), start, deadline, now))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return self.state()

    def report(self):
        with self.connect() as db:
            state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            runs = [dict(zip(('id','started','stopped','heartbeat'), row)) for row in db.execute(
                'SELECT id,started,stopped,heartbeat FROM cloud_runs ORDER BY id DESC LIMIT 100')]
            total = db.execute('SELECT count(*) FROM cloud_rounds').fetchone()[0]
            recent = [json.loads(row[0]) for row in db.execute(
                'SELECT payload FROM cloud_rounds ORDER BY id DESC LIMIT 20')]
            counts = {}
            for row in db.execute('SELECT payload FROM events'):
                action = json.loads(row[0]).get('outcome', {}).get('action', 'UNKNOWN')
                counts[action] = counts.get(action, 0) + 1
        gaps = [max(0, newer['started'] - (older['stopped'] or older['heartbeat']))
                for newer, older in zip(runs, runs[1:])]
        return dict(mode=MODE, real_trading=False, blockchain_transactions_sent=0,
                    control=self.state(), entries_allowed=self.entries_allowed(),
                    strategy=dict(buy_usd=5, tp_pct=20, sl_pct=-10, max_positions=2),
                    cost_model=dict(fee_per_side=.013, fixed_usd_per_side=.05,
                                    adverse_slippage_bps_per_side=50, measured=False),
                    durable_state=state, event_counts=counts, rounds=total, recent_rounds=recent,
                    process_runs=runs, restart_gaps_seconds=gaps,
                    continuous_24h_proven=False,
                    uptime_note='Process records and heartbeat gaps are evidence, not an external 24h availability proof.')


def guarded_bot(control, stop):
    class GuardedBot(PersistentPaperBot):
        def process(self, event):
            # The same cross-process lock covers OFF and the final entry decision.
            with entry_lock(control.directory):
                if event.get('type') == 'candidate' and (stop.is_set() or not control.entries_allowed()):
                    return dict(action='PAPER_PAUSED', mode='PAPER', reasons=['entries_off_or_session_expired'])
                return super().process(event)
    return GuardedBot


PAGE = '''<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Solana AI Sniper — PAPER</title><style>body{font:16px system-ui;max-width:760px;margin:32px auto;padding:16px;background:#111827;color:#eee}button,input{padding:12px;margin:5px;font-size:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere}strong{color:#6ee7b7}</style>
<h1>Solana AI Sniper</h1><p><strong>PAPER ONLY · REAL OFF</strong></p>
<p>BUY simulasi $5 · TP +20% · SL −10% · Maksimal 2 posisi.</p>
<label>Token kontrol <input id="token" type="password" autocomplete="off"></label>
<p><button onclick="act('on')">ON</button><button onclick="act('off')">OFF</button></p>
<p>OFF menghentikan pencarian dan BUY baru. Posisi yang terbuka tetap dipantau untuk SELL simulasi. Jendela BUY berhenti 24 jam setelah ON pertama, termasuk setelah restart.</p>
<p id="notice"></p><pre id="result">Masukkan token kontrol untuk melihat laporan. Ini bukan private key wallet.</pre>
<script>
async function load(path,method='GET'){let r=await fetch('/api/'+path,{method,headers:{Authorization:'Bearer '+document.getElementById('token').value}});let v=await r.json();if(!r.ok)throw Error(v.error||'Permintaan gagal');return v}
async function report(){if(!document.getElementById('token').value)return;try{document.getElementById('result').textContent=JSON.stringify(await load('report'),null,2)}catch(e){document.getElementById('notice').textContent=e.message}}
async function act(a){try{await load(a,'POST');document.getElementById('notice').textContent=a==='on'?'ON: simulasi diizinkan setelah semua filter lulus.':'OFF: BUY baru dihentikan.';await report()}catch(e){document.getElementById('notice').textContent=e.message}}
document.getElementById('token').addEventListener('change',report);setInterval(report,15000);
</script></html>'''


def http_server(control, token, port, alive, host='0.0.0.0'):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log Authorization or user-provided input.

        def answer(self, status, obj, html=False):
            data = (obj if html else json.dumps(obj, allow_nan=False)).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/':
                return self.answer(200, PAGE, html=True)
            if self.path == '/healthz':
                return self.answer(200 if alive() else 503, dict(mode=MODE, worker_alive=alive()))
            if not self.auth():
                return
            if self.path == '/api/report':
                return self.answer(200, control.report())
            self.answer(404, dict(error='not_found'))

        def auth(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer ' + token):
                self.answer(401, dict(error='unauthorized'))
                return False
            return True

        def do_POST(self):
            if not self.auth():
                return
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Length', '0') != '0':
                return self.answer(400, dict(error='request_body_not_supported'))
            if self.path not in ('/api/on', '/api/off'):
                return self.answer(404, dict(error='not_found'))
            try:
                self.answer(200, control.switch(self.path == '/api/on'))
            except ValueError as error:
                self.answer(409, dict(error=str(error)))

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


class Worker:
    def __init__(self, control, interval=30, reader_factory=None):
        self.control, self.interval = control, interval
        self.stop = threading.Event()
        self.reader_factory = reader_factory or engine.Reader

    def run(self, max_rounds=None):
        enforce_paper()
        with open(self.control.directory / 'worker.lock', 'a') as singleton:
            fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.control.connect() as db:
                now = time.time()
                run_id = db.execute('INSERT INTO cloud_runs(started,heartbeat,pid) VALUES(?,?,?)',
                                    (now, now, os.getpid())).lastrowid
            original_bot = engine.PersistentPaperBot
            engine.PersistentPaperBot = guarded_bot(self.control, self.stop)
            reader = None
            completed = 0
            try:
                def factory(store):
                    nonlocal reader
                    if reader is None:
                        reader = self.reader_factory(store)
                        request = reader.request
                        def stopping_request(*args, **kwargs):
                            if self.stop.is_set():
                                raise InterruptedError('worker_stopping')
                            if reader._cloud_entry_phase and not self.control.entries_allowed():
                                raise InterruptedError('entries_paused')
                            return request(*args, **kwargs)
                        reader.request = stopping_request
                        discover = reader.discover
                        def gated_discover(*args, **kwargs):
                            if self.stop.is_set() or not self.control.entries_allowed():
                                return [], [], dict(entries_paused=True, new_unique_addresses=0)
                            reader._cloud_entry_phase = True
                            return discover(*args, **kwargs)
                        reader.discover = gated_discover
                        if hasattr(reader, 'limits'):
                            def paced_sleep(seconds):
                                if self.stop.wait(seconds):
                                    raise InterruptedError('worker_stopping')
                            for limiter in reader.limits.values():
                                limiter.sleep = paced_sleep
                    reader.store = store
                    reader._cloud_entry_phase = False
                    reader.requests = []
                    return reader

                while not self.stop.is_set() and (max_rounds is None or completed < max_rounds):
                    started = time.time()
                    with self.control.connect() as db:
                        db.execute('UPDATE cloud_runs SET heartbeat=? WHERE id=?', (started, run_id))
                    args = SimpleNamespace(state_db=str(self.control.database), rounds=1, interval=0,
                        max_security=3, max_tokens=120, onchain_transactions=2,
                        output=str(self.control.directory / 'latest_round.json'))
                    try:
                        evidence = engine.run(args, reader_factory=factory)
                        report = dict(started=started, finished=time.time(), summary=evidence['summary'],
                                      errors=evidence['errors'], request_count=len(evidence['requests']),
                                      entries_paused=not self.control.entries_allowed(),
                                      discovery=[r.get('discovery', {}) for r in evidence['rounds']])
                        with gzip.open(self.control.directory / 'latest_round.json.gz', 'wt') as out:
                            json.dump(evidence, out, allow_nan=False)
                        self.control.directory.joinpath('latest_round.json').unlink(missing_ok=True)
                    except Exception as error:
                        # Never reset state or fall back to an unsafe strategy.
                        report = dict(started=started, finished=time.time(), fatal_round_error=engine.safe_error(error))
                    with self.control.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        db.execute('INSERT INTO cloud_rounds(finished,payload) VALUES(?,?)',
                                   (time.time(), json.dumps(report, allow_nan=False)))
                        db.execute('UPDATE cloud_runs SET heartbeat=? WHERE id=?', (time.time(), run_id))
                        db.commit()
                    completed += 1
                    print(json.dumps(dict(mode=MODE, completed_round=completed, **report)), flush=True)
                    if max_rounds is None or completed < max_rounds:
                        self.stop.wait(self.interval)
            finally:
                engine.PersistentPaperBot = original_bot
                if reader is not None and reader.store is not None:
                    with contextlib.suppress(sqlite3.Error):
                        reader.store.close()
                with self.control.connect() as db:
                    now = time.time()
                    db.execute('UPDATE cloud_runs SET stopped=?,heartbeat=? WHERE id=?', (now, now, run_id))
                    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=os.getenv('SNIPER_DATA_DIR', '/var/data/sniper'))
    parser.add_argument('--seed-db', default=os.getenv('SNIPER_SEED_DB'))
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '10000')))
    parser.add_argument('--interval', type=float, default=30)
    parser.add_argument('--max-rounds', type=int)
    args = parser.parse_args()
    enforce_paper()
    token = os.environ.get('SNIPER_CONTROL_TOKEN', '')
    if len(token) < 32:
        raise ValueError('SNIPER_CONTROL_TOKEN must contain at least 32 characters')
    control = Control(args.data_dir, args.seed_db, os.getenv('SNIPER_INITIAL_ON') == '1')
    worker = Worker(control, args.interval)
    server = http_server(control, token, args.port, lambda: not worker.stop.is_set())
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    def shutdown(*_):
        worker.stop.set()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        worker.run(args.max_rounds)
    finally:
        worker.stop.set()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
