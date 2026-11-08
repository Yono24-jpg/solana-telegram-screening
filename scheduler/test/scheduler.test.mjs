import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import worker, { SchedulerCoordinator } from '../worker.mjs';

const INTERVAL = 300_000;

const NOW = Math.floor(Date.now() / INTERVAL) * INTERVAL + 10_000;
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

class Storage {
  constructor() { this.data = new Map(); this.queue = Promise.resolve(); }
  async get(key) { return structuredClone(this.data.get(key)); }
  async put(key, value) { this.data.set(key, structuredClone(value)); }
  transaction(fn) {
    const run = this.queue.then(async () => {
      const backup = structuredClone(this.data);
      try { return await fn(this); } catch (e) { this.data = backup; throw e; }
    });
    this.queue = run.catch(() => {});
    return run;
  }
}

function fixture({ runs = [], post = 204, workflow, runResponse, failGet = false, failPost = false } = {}) {
  const storage = new Storage();
  const env = { GITHUB_TOKEN: 'fake-test-token', SCHEDULER_ENABLED: 'true', SCHEDULER_ADMIN_TOKEN: 'fake-admin' };
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options });
    assert.ok(url.startsWith('https://api.github.com/repos/Yono24-jpg/solana-telegram-screening/actions/workflows/screen.yml'));
    assert.equal(options.redirect, 'manual');
    if (options.method === 'POST') {
      if (failPost) throw new Error('sensitive provider text fake-test-token');
      assert.deepEqual(JSON.parse(options.body), { ref: 'main' });
      const state = await storage.get('state');
      assert.ok(Object.values(state.slots).some(x => x.outcome === 'dispatch_reserved'));
      return new Response(null, { status: post });
    }
    if (failGet) throw new Error('sensitive fake-test-token');
    return Response.json(url.includes('/runs?') ? runResponse || { workflow_runs: runs }
      : workflow || { path: '.github/workflows/screen.yml', state: 'active' });
  };
  const instance = () => new SchedulerCoordinator({ storage }, env);
  return { storage, env, calls, instance, tick: (time = NOW, at = NOW, origin = 'cron') => instance().tick({ scheduledTime: time, origin }, at),
    posts: () => calls.filter(x => x.method === 'POST') };
}

function run(status = 'completed', age = 600_000, extra = {}) {
  return { id: 42, status, head_branch: 'main', path: '.github/workflows/screen.yml',
    created_at: new Date(NOW - age).toISOString(), ...extra };
}

test('dispatch is fixed to existing screen.yml/main and reserved before POST', async () => {
  const f = fixture();
  const result = await f.tick();
  assert.equal(result.outcome, 'dispatch_accepted');
  assert.equal(result.http_status, 204);
  assert.equal(f.posts().length, 1);
});

test('twenty simultaneous deliveries, including reconstructed instances, post only once', async () => {
  const f = fixture();
  const result = await Promise.all(Array.from({ length: 20 }, () => f.tick()));
  assert.equal(result.filter(x => x.outcome === 'dispatch_accepted').length, 1);
  assert.equal(f.posts().length, 1);
  assert.equal((await f.tick()).outcome, 'duplicate_slot');
});

test('nearby adjacent slots share a durable cooldown; later normal slot can proceed', async () => {
  const f = fixture();
  assert.equal((await f.tick(NOW + 280_000, NOW + 280_000)).outcome, 'dispatch_accepted');
  assert.equal((await f.tick(NOW + 300_000, NOW + 300_000)).outcome, 'dispatch_cooldown');
  assert.equal((await f.tick(NOW + 600_000, NOW + 600_000)).outcome, 'dispatch_accepted');
  assert.equal(f.posts().length, 2);
});

test('a little cron jitter does not drop an otherwise eligible five-minute slot', async () => {
  const f = fixture();
  await f.tick();
  assert.equal((await f.tick(NOW + INTERVAL - 1000, NOW + INTERVAL - 1000)).outcome, 'dispatch_accepted');
});

for (const status of ['queued', 'in_progress', 'waiting', 'requested', 'pending']) {
  test(`no dispatch while existing scanner is ${status}`, async () => {
    const f = fixture({ runs: [run(status)] });
    assert.equal((await f.tick()).outcome, 'scanner_already_active');
    assert.equal(f.posts().length, 0);
  });
}

test('recent native/manual scanner runs suppress fallback', async () => {
  const f = fixture({ runs: [run('completed', 60_000)] });
  assert.equal((await f.tick()).outcome, 'recent_scanner_run');
  assert.equal(f.posts().length, 0);
});

test('disabled or missing secret never calls GitHub', async () => {
  const f = fixture();
  f.env.SCHEDULER_ENABLED = 'false';
  assert.equal((await f.tick()).outcome, 'disabled');
  f.env.SCHEDULER_ENABLED = 'true';
  delete f.env.GITHUB_TOKEN;
  assert.equal((await f.tick()).outcome, 'missing_github_secret');
  assert.equal(f.calls.length, 0);
});

test('stale, future, noninteger, and foreign-origin events are refused', async () => {
  const f = fixture();
  for (const [time, origin] of [[NOW - 2 * INTERVAL - 1, 'cron'], [NOW + 30_001, 'cron'], [1.5, 'cron'], [NOW, 'force']]) {
    assert.equal((await f.tick(time, NOW, origin)).outcome, 'invalid_or_stale_tick');
  }
  assert.equal(f.calls.length, 0);
});

test('workflow identity or inactive state prevents dispatch', async () => {
  for (const workflow of [{ path: '.github/workflows/evil.yml', state: 'active' }, { path: '.github/workflows/screen.yml', state: 'disabled_manually' }]) {
    const f = fixture({ workflow });
    assert.equal((await f.tick()).outcome, 'workflow_inactive_or_mismatch');
    assert.equal(f.posts().length, 0);
  }
});

test('invalid or mismatched run data fails closed', async () => {
  for (const options of [{ runResponse: {} }, { runs: [run('completed', 1e6, { path: 'wrong' })] },
    { runs: [run('new_unknown_status')] }, { runs: [run('completed', 1e6, { created_at: 'bad' })] }]) {
    const f = fixture(options);
    assert.notEqual((await f.tick()).outcome, 'dispatch_accepted');
    assert.equal(f.posts().length, 0);
  }
});

test('GitHub check outage and permission errors do not dispatch or expose provider error', async () => {
  const f = fixture({ failGet: true });
  assert.equal((await f.tick()).outcome, 'github_check_unavailable');
  assert.equal(f.posts().length, 0);
  assert.ok(!JSON.stringify(await f.storage.get('state')).includes('fake-test-token'));
  const g = fixture();
  globalThis.fetch = async () => new Response(null, { status: 403 });
  assert.equal((await g.tick()).http_status, 403);
  assert.equal(g.posts().length, 0);
});

test('ambiguous POST timeout is recorded and not retried after restart', async () => {
  const f = fixture({ failPost: true });
  assert.equal((await f.tick()).outcome, 'dispatch_unknown_no_retry');
  assert.equal((await f.tick()).outcome, 'duplicate_slot');
  assert.equal(f.posts().length, 1);
  assert.ok(!JSON.stringify(await f.storage.get('state')).includes('sensitive'));
});

test('definitive POST rejection is retained and not immediately retried', async () => {
  const f = fixture({ post: 403 });
  assert.equal((await f.tick()).outcome, 'dispatch_rejected');
  assert.equal((await f.tick()).outcome, 'duplicate_slot');
  assert.equal(f.posts().length, 1);
});

test('storage failure before reservation means no POST', async () => {
  const f = fixture();
  const put = f.storage.put.bind(f.storage);
  f.storage.put = async (key, data) => {
    if (Object.values(data.slots).some(x => x.outcome === 'dispatch_reserved')) throw new Error('storage unavailable');
    return put(key, data);
  };
  assert.equal((await f.tick()).outcome, 'github_check_unavailable');
  assert.equal(f.posts().length, 0);
});

test('history pruning bounds storage while retaining recent replay protection', async () => {
  const f = fixture();
  const slot = Math.floor(NOW / INTERVAL);
  await f.storage.put('state', { slots: { [slot - 300]: { at: 1 }, [slot - 1]: { at: NOW - INTERVAL } }, nextDispatchAfter: 0 });
  await f.tick();
  const state = await f.storage.get('state');
  assert.equal(state.slots[slot - 300], undefined);
  assert.ok(state.slots[slot - 1]);
});

test('public HTTP requests cannot trigger, force, configure or read private status', async () => {
  const f = fixture();
  for (const path of ['/admin/tick', '/admin/status']) {
    assert.equal((await worker.fetch(new Request(`https://worker.test${path}`, { method: 'POST' }), f.env)).status, 401);
  }
  for (const path of ['/', '/run', '/?force=1', '/tick']) {
    assert.equal((await worker.fetch(new Request(`https://worker.test${path}`), f.env)).status, 404);
  }
  const health = await (await worker.fetch(new Request('https://worker.test/health'), f.env)).text();
  assert.ok(!health.includes('fake-test-token'));
  assert.equal(f.posts().length, 0);
});

test('authorized test ignores caller body and uses same durable path as cron', async () => {
  const f = fixture();
  const forwarded = [];
  f.env.SCHEDULER_LOCK = { idFromName: x => x, get: () => ({ fetch: async req => {
    forwarded.push(await req.json()); return Response.json({ outcome: 'duplicate_slot' });
  } }) };
  const request = new Request('https://worker.test/admin/tick', { method: 'POST', headers: { Authorization: 'Bearer fake-admin' },
    body: JSON.stringify({ target: 'other/repo', force: true, scheduledTime: 1 }) });
  assert.equal((await worker.fetch(request, f.env)).status, 200);
  assert.equal(forwarded[0].origin, 'manual_test');
  assert.ok(forwarded[0].scheduledTime > NOW - INTERVAL);
  assert.equal(forwarded[0].target, undefined);
});
