import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import worker, { githubIdentity, SchedulerCoordinator } from '../worker.mjs';

const now = Math.floor(Date.now() / 1000);
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: 'jwk' }), kid: 'fixture', alg: 'RS256', use: 'sig' };
const claims = { iss: 'https://token.actions.githubusercontent.com', aud: 'mail-narrative-ai',
  repository: 'Yono24-jpg/solana-telegram-screening', repository_id: '1439952946', repository_owner_id: '290577634',
  ref: 'refs/heads/main', workflow_ref: 'Yono24-jpg/solana-telegram-screening/.github/workflows/screen.yml@refs/heads/main',
  event_name: 'workflow_dispatch', iat: now - 10, nbf: now - 10, exp: now + 300 };
function request(changes = {}, key = privateKey) {
  const body = Buffer.from(JSON.stringify({ ...claims, ...changes })).toString('base64url');
  const header = Buffer.from(JSON.stringify({ alg: 'RS256', kid: 'fixture' })).toString('base64url');
  const token = `${header}.${body}.${sign('RSA-SHA256', Buffer.from(`${header}.${body}`), key).toString('base64url')}`;
  return new Request('https://scheduler/ai/entities', { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
}
const fetchKeys = async url => { assert.equal(url, 'https://token.actions.githubusercontent.com/.well-known/jwks'); return Response.json({ keys: [jwk] }); };

test('signed main workflow identity succeeds; wrong repo, audience, branch and expiry fail', async () => {
  assert.equal(await githubIdentity(request(), now, fetchKeys), true);
  for (const changes of [{ aud: 'other' }, { repository_id: '1' }, { repository_owner_id: '1' }, { ref: 'refs/heads/other' },
    { repository: 'attacker/repo' }, { workflow_ref: 'other' }, { exp: now - 1 }, { iat: now - 1000 }, { nbf: now + 60 }, { event_name: 'pull_request' }]) {
    assert.equal(await githubIdentity(request(changes), now, fetchKeys), false);
  }
});
test('tampered JWT and unknown key fail closed', async () => {
  const r = request(); const auth = r.headers.get('Authorization');
  const parts = auth.slice(7).split('.'); parts[1] = Buffer.from(JSON.stringify({ ...claims, actor: 'forged' })).toString('base64url');
  assert.equal(await githubIdentity(new Request(r.url, { headers: { Authorization: 'Bearer ' + parts.join('.') } }), now, fetchKeys), false);
  assert.equal(await githubIdentity(request(), now, async () => Response.json({ keys: [] })), false);
});
test('public callers cannot invoke inference', async () => {
  const r = await worker.fetch(new Request('https://scheduler/ai/entities', { method: 'POST' }), {});
  assert.equal(r.status, 401);
});
class Storage {
  constructor() { this.data = new Map(); this.queue = Promise.resolve(); }
  async get(k) { return structuredClone(this.data.get(k)); }
  async put(k, v) { this.data.set(k, structuredClone(v)); }
  transaction(fn) { const promise = this.queue.then(() => fn(this)); this.queue = promise.catch(() => {}); return promise; }
}
test('AI budget is claimed before inference, concurrent calls and restart use durable cache', async () => {
  const storage = new Storage(); let calls = 0;
  const env = { AI: { async run(model, input) { calls++; assert.equal((await storage.get('narrative_ai')).calls, 1);
    assert.equal(input.max_tokens, 400); return { response: { entities: ['GTA VI'] }, model }; } } };
  const make = () => new SchedulerCoordinator({ storage }, env);
  const input = [{ title: 'GTA VI trailer' }];
  const values = await Promise.all(Array.from({ length: 8 }, () => make().extractNarrative(input, now * 1000)));
  assert.equal(calls, 1); assert.ok(values.some(x => x.status === 'ok'));
  assert.deepEqual((await make().extractNarrative(input, now * 1000 + 100)).entities, ['GTA VI']);
  const saved = await storage.get('narrative_ai'); await storage.put('narrative_ai', { ...saved, at: 1, calls: 8 });
  assert.equal((await make().extractNarrative(input, now * 1000)).status, 'daily_budget_reached');
  assert.equal(calls, 1);
});
test('provider failure consumes a reservation and never leaks provider text', async () => {
  const storage = new Storage(); const instance = new SchedulerCoordinator({ storage }, { AI: { run() { throw Error('sensitive'); } } });
  const result = await instance.extractNarrative([{ title: 'News' }], now * 1000);
  assert.equal(result.status, 'provider_unavailable'); assert.equal((await storage.get('narrative_ai')).calls, 1);
  assert.equal(JSON.stringify(result).includes('sensitive'), false);
});
