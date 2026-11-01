"""Durable PAPER-only state and conservative request pacing; no wallet support."""
import copy
import json
import math
import sqlite3
import time
from collections import deque
from solana_sniper_paper import PaperBot, number


class RateLimiter:
    def __init__(self, limit, window=60, spacing=0, clock=time.monotonic, sleep=time.sleep):
        self.limit, self.window, self.spacing = limit, window, spacing
        self.clock, self.sleep = clock, sleep
        self.calls = deque()
        self.blocked_until = 0

    def wait(self):
        now = self.clock()
        while self.calls and now-self.calls[0] >= self.window:
            self.calls.popleft()
        ready = max(now, self.blocked_until,
                    self.calls[-1]+self.spacing if self.calls else now,
                    self.calls[0]+self.window if len(self.calls) >= self.limit else now)
        delay = ready-now
        if delay > 60:
            raise RuntimeError('rate_limit_cooldown_active')
        if delay > 0:
            self.sleep(delay)
        self.calls.append(self.clock())

    def cooldown(self, seconds):
        self.blocked_until = max(self.blocked_until, self.clock()+seconds)


class PersistentPaperBot(PaperBot):
    """One SQLite transaction covers filter decision, position, mint dedup and log.
    Concurrent instances reload under BEGIN IMMEDIATE, enforcing 2 total slots.
    No external execution exists, so a crash can only roll back a paper decision.
    """
    def __init__(self, database, fee=.013, fixed=.05, slippage_bps=50):
        super().__init__(fee, fixed, slippage_bps)
        self.config = dict(fee=fee, fixed=fixed, slippage_bps=slippage_bps)
        self.db = sqlite3.connect(str(database), timeout=10, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cache (kind TEXT, key TEXT, payload TEXT NOT NULL,
                                             PRIMARY KEY(kind,key));
        ''')
        self.pins = {}
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()
            if row is None:
                self._save()
            else:
                self._load(json.loads(row[0]))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.db.close()
            raise

    def _snapshot(self):
        return dict(schema=1, mode='PAPER_ONLY_REAL_OFF', config=self.config,
                    positions=self.positions, seen=sorted(self.seen), pnl=self.pnl,
                    clock=self.clock if math.isfinite(self.clock) else None, pins=self.pins)

    def _load(self, state):
        if (state.get('schema') != 1 or state.get('mode') != 'PAPER_ONLY_REAL_OFF'
            or state.get('config') != self.config):
            raise ValueError('State schema/mode/cost configuration mismatch; refusing reset')
        positions, seen, pins = state['positions'], set(state['seen']), state['pins']
        if not isinstance(positions, dict) or len(positions) > 2 or not set(positions) <= seen:
            raise ValueError('Invalid saved positions')
        for mint, position in positions.items():
            if not pins.get(mint) or not all(number(position.get(k)) and position[k] > 0
                                            for k in ('entry','quantity','cost')):
                raise ValueError('Invalid saved position/pair')
        if not number(state['pnl']) or (state['clock'] is not None and not number(state['clock'])):
            raise ValueError('Invalid saved PnL/clock')
        self.positions, self.seen, self.pins = positions, seen, pins
        self.pnl, self.clock = state['pnl'], state['clock'] if state['clock'] is not None else -math.inf

    def _save(self):
        payload = json.dumps(self._snapshot(), allow_nan=False)
        self.db.execute('INSERT INTO state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (payload,))

    def refresh(self):
        self._load(json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]))

    def process(self, event):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.refresh()
            if event.get('type') == 'candidate' and not event.get('pair_address'):
                outcome = dict(mode='PAPER', action='REJECT', mint=event.get('mint'),
                               reasons=['missing_pair_address'], positions=len(self.positions))
            else:
                outcome = super().process(event)
            if outcome['action'] == 'PAPER_BUY':
                self.pins[event['mint']] = event['pair_address']
            if outcome['action'] == 'PAPER_SELL':
                self.pins.pop(event['mint'], None)
            self._save()
            self.db.execute('INSERT INTO events(payload) VALUES(?)',
                            (json.dumps(dict(event=event, outcome=outcome), allow_nan=False),))
            self.db.commit()
            return outcome
        except BaseException:
            self.db.rollback()
            self.refresh()
            raise

    def cache_get(self, kind, key):
        row = self.db.execute('SELECT payload FROM cache WHERE kind=? AND key=?',(kind,key)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_put(self, kind, key, value):
        self.db.execute('INSERT INTO cache VALUES(?,?,?) ON CONFLICT(kind,key) DO UPDATE SET payload=excluded.payload',
                        (kind,key,json.dumps(value,allow_nan=False)))

    def cache_items(self, kind):
        return [(key,json.loads(payload)) for key,payload in self.db.execute(
            'SELECT key,payload FROM cache WHERE kind=? ORDER BY key',(kind,)).fetchall()]

    def snapshot(self):
        self.refresh()
        return copy.deepcopy(self._snapshot())

    def close(self):
        self.db.close()
