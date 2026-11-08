import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Miniflare, Log, LogLevel, convertV4MiniflareOptions } from 'miniflare';

test('real workerd SQLite object serializes parallel cron ticks and restores the claim after restart', { timeout: 30_000 }, async () => {
  const persist = await mkdtemp(join(tmpdir(), 'mail-scheduler-test-'));
  const time = Date.now();
  let posts = 0;
  const options = {
    name: 'mail-solana-scheduler', modules: true, scriptPath: fileURLToPath(new URL('../worker.mjs', import.meta.url)),
    compatibilityDate: '2026-11-08', log: new Log(LogLevel.ERROR),
    bindings: { GITHUB_TOKEN: 'fixture-only', SCHEDULER_ADMIN_TOKEN: 'fixture-admin', SCHEDULER_ENABLED: 'true' },
    durableObjects: { SCHEDULER_LOCK: { className: 'SchedulerCoordinator', useSQLite: true } },
    durableObjectsPersist: persist,
    outboundService: async request => {
      assert.ok(request.url.startsWith('https://api.github.com/repos/Yono24-jpg/solana-telegram-screening/actions/workflows/screen.yml'));
      if (request.method === 'POST') {
        assert.deepEqual(await request.json(), { ref: 'main' });
        posts++;
        return new Response(null, { status: 204 });
      }
      return Response.json(request.url.includes('/runs?') ? { workflow_runs: [] }
        : { path: '.github/workflows/screen.yml', state: 'active' });
    },
  };
  const runtimeOptions = convertV4MiniflareOptions(options);
  runtimeOptions.resourcePersistencePath = persist;
  let mf = new Miniflare(runtimeOptions);
  const fire = async () => {
    const ns = await mf.getDurableObjectNamespace('SCHEDULER_LOCK');
    return (await ns.get(ns.idFromName('Yono24-jpg/solana-telegram-screening:screen.yml:main')).fetch('https://coordinator/tick',
      { method: 'POST', body: JSON.stringify({ scheduledTime: time, origin: 'cron' }) })).json();
  };
  try {
    const result = await Promise.all(Array.from({ length: 12 }, fire));
    assert.equal(result.filter(x => x.outcome === 'dispatch_accepted').length, 1, JSON.stringify(result));
    assert.equal(posts, 1);
    assert.equal((await mf.dispatchFetch('https://worker.test/admin/tick', { method: 'POST' })).status, 401);
    await mf.dispose();
    mf = new Miniflare(runtimeOptions);
    assert.equal((await fire()).outcome, 'duplicate_slot');
    assert.equal(posts, 1);
  } finally {
    await mf.dispose();
    await rm(persist, { recursive: true, force: true });
  }
});
