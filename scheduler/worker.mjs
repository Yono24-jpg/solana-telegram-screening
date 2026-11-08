// This Worker can dispatch only the existing scanner. It has no Telegram or wallet access.
const TARGET = 'Yono24-jpg/solana-telegram-screening';
const WORKFLOW = 'screen.yml';
const INTERVAL = 300_000;
const COOLDOWN = INTERVAL - 5_000; // Tolerate small cron delivery jitter, not an extra dispatch endpoint.
const ROOT = `https://api.github.com/repos/${TARGET}/actions/workflows/${WORKFLOW}`;
const ACTIVE = new Set(['queued', 'in_progress', 'waiting', 'requested', 'pending']);

function json(data, status = 200) {
  return Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });
}

async function authorized(request, secret) {
  if (!secret) return false;
  const value = request.headers.get('Authorization') || '';
  const digest = async (s) => new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
  const [a, b] = await Promise.all([digest(value), digest(`Bearer ${secret}`)]);
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
  return difference === 0;
}

function coordinator(env) {
  return env.SCHEDULER_LOCK.get(env.SCHEDULER_LOCK.idFromName(`${TARGET}:${WORKFLOW}:main`));
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path === '/health' && request.method === 'GET') {
      return json({ service: 'mail-solana-scheduler', version: '1.0', interval_seconds: 300,
        configured: Boolean(env.GITHUB_TOKEN && env.SCHEDULER_ADMIN_TOKEN && env.SCHEDULER_LOCK),
        enabled: env.SCHEDULER_ENABLED === 'true' });
    }
    if (!['/admin/status', '/admin/tick'].includes(path)) return json({ error: 'not_found' }, 404);
    if (!(await authorized(request, env.SCHEDULER_ADMIN_TOKEN))) return json({ error: 'unauthorized' }, 401);
    if (!env.SCHEDULER_LOCK) return json({ error: 'missing_lock_binding' }, 503);
    if (path === '/admin/status' && request.method === 'GET') {
      return coordinator(env).fetch(new Request('https://coordinator/status'));
    }
    if (path === '/admin/tick' && request.method === 'POST') {
      // No caller-controlled repository, workflow, branch, time, or force bypass.
      return coordinator(env).fetch(new Request('https://coordinator/tick', {
        method: 'POST', body: JSON.stringify({ scheduledTime: Date.now(), origin: 'manual_test' }),
      }));
    }
    return json({ error: 'method_not_allowed' }, 405);
  },
  async scheduled(controller, env) {
    if (!env.SCHEDULER_LOCK) throw new Error('missing_lock_binding');
    const response = await coordinator(env).fetch(new Request('https://coordinator/tick', {
      method: 'POST', body: JSON.stringify({ scheduledTime: controller.scheduledTime, origin: 'cron' }),
    }));
    const result = await response.json();
    // Only our bounded, allowlisted outcome; never provider bodies, headers, tokens or errors.
    console.log('SCHEDULER_TICK', JSON.stringify(result));
    if (!response.ok || !['dispatch_accepted', 'duplicate_slot', 'dispatch_cooldown',
      'scanner_already_active', 'recent_scanner_run', 'disabled'].includes(result.outcome)) {
      throw new Error('scheduler_tick_failed');
    }
  },
};

export class SchedulerCoordinator {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; }

  async fetch(request) {
    if (new URL(request.url).pathname === '/status' && request.method === 'GET') {
      const state = await this.ctx.storage.get('state') || {};
      return json({ target: TARGET, workflow: WORKFLOW, ref: 'main',
        next_dispatch_after: state.nextDispatchAfter || null,
        history: Object.values(state.slots || {}).sort((a, b) => b.at - a.at).slice(0, 30) });
    }
    if (new URL(request.url).pathname !== '/tick' || request.method !== 'POST') return json({ error: 'not_found' }, 404);
    let input;
    try { input = await request.json(); } catch { return json({ error: 'invalid_tick' }, 400); }
    return json(await this.tick(input), 200);
  }

  async github(path, method = 'GET', body) {
    const response = await fetch(ROOT + path, {
      method, redirect: 'manual', signal: AbortSignal.timeout(10_000),
      headers: { Authorization: `Bearer ${this.env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'mail-solana-scheduler/1.0', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (method === 'POST') return { status: response.status };
    if (response.status !== 200) return { status: response.status };
    return { status: 200, data: await response.json() };
  }

  async save(slot, fields) {
    await this.ctx.storage.transaction(async tx => {
      const state = await tx.get('state') || { slots: {} };
      state.slots[slot] = { ...state.slots[slot], ...fields };
      await tx.put('state', state);
    });
  }

  async tick({ scheduledTime, origin }, now = Date.now()) {
    if (!Number.isSafeInteger(scheduledTime) || scheduledTime > now + 30_000 || now - scheduledTime > 2 * INTERVAL ||
        !['cron', 'manual_test'].includes(origin)) return { outcome: 'invalid_or_stale_tick' };
    if (this.env.SCHEDULER_ENABLED !== 'true') return { outcome: 'disabled' };
    if (!this.env.GITHUB_TOKEN) return { outcome: 'missing_github_secret' };
    const slot = Math.floor(scheduledTime / INTERVAL);
    // Strongly consistent durable claim. No network I/O inside the transaction.
    const claim = await this.ctx.storage.transaction(async tx => {
      const state = await tx.get('state') || { slots: {}, nextDispatchAfter: 0 };
      for (const key of Object.keys(state.slots)) if (Number(key) < slot - 288) delete state.slots[key];
      if (state.slots[slot]) return 'duplicate_slot';
      const outcome = state.nextDispatchAfter > now ? 'dispatch_cooldown' : 'checking';
      state.slots[slot] = { slot, at: now, origin, outcome };
      // Also serialize adjacent-slot arrivals and survive restart while checking GitHub.
      if (outcome === 'checking') state.nextDispatchAfter = now + COOLDOWN;
      await tx.put('state', state);
      return outcome;
    });
    if (claim !== 'checking') return { slot, outcome: claim };
    const finish = async (outcome, extra = {}) => {
      await this.save(slot, { outcome, ...extra });
      return { slot, outcome, ...extra };
    };
    let dispatchStarted = false;
    try {
      const workflow = await this.github('');
      if (workflow.status !== 200) return finish('workflow_check_failed', { http_status: workflow.status });
      if (workflow.data?.path !== '.github/workflows/screen.yml' || workflow.data?.state !== 'active') {
        return finish('workflow_inactive_or_mismatch');
      }
      const result = await this.github('/runs?branch=main&per_page=100');
      if (result.status !== 200) return finish('run_check_failed', { http_status: result.status });
      const runs = result.data?.workflow_runs;
      if (!Array.isArray(runs)) return finish('invalid_run_response');
      for (const run of runs) {
        if (run.head_branch !== 'main' || run.path !== '.github/workflows/screen.yml') return finish('run_identity_mismatch');
        if (ACTIVE.has(run.status)) return finish('scanner_already_active', { run_id: run.id });
        if (run.status !== 'completed') return finish('unknown_run_status');
        const created = Date.parse(run.run_started_at || run.created_at);
        if (!Number.isFinite(created) || created > now + 30_000) return finish('invalid_run_time');
        if (now - created < COOLDOWN) return finish('recent_scanner_run', { run_id: run.id });
      }
      // Reserve durably BEFORE POST. Timeout/crash after this point is never retried in this slot.
      await this.save(slot, { outcome: 'dispatch_reserved', dispatch_at: now });
      dispatchStarted = true;
      const response = await this.github('/dispatches', 'POST', { ref: 'main' });
      return finish(response.status === 204 ? 'dispatch_accepted' : 'dispatch_rejected', { http_status: response.status });
    } catch {
      // Error bodies may echo credentials. Store only a fixed diagnosis.
      return finish(dispatchStarted ? 'dispatch_unknown_no_retry' : 'github_check_unavailable');
    }
  }
}
