"""Deploy only mail-solana-scheduler. Credentials never enter logs or artifacts."""
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.request

NAME = 'mail-solana-scheduler'
REPO = 'Yono24-jpg/solana-telegram-screening'
WORKFLOW = 'screen.yml'
CF_ROOT = 'https://api.cloudflare.com/client/v4/'
GH_ROOT = 'https://api.github.com/'
HERE = Path(__file__).resolve().parent
REPORT = {'service': NAME, 'github_token_secret_present': bool(os.environ.get('SCHEDULER_GITHUB_TOKEN')),
          'cloudflare_token_secret_present': bool(os.environ.get('CLOUDFLARE_API_TOKEN'))}


class SafeError(Exception):
    pass


def request(url, method='GET', body=None, token=None, content_type='application/json', timeout=25):
    # No redirects with authentication. Never include response bodies or exception text in errors.
    headers = {'User-Agent': NAME + '/1.0', 'Accept': 'application/json', 'Content-Type': content_type}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if url.startswith(GH_ROOT):
        headers['Accept'] = 'application/vnd.github+json'
        headers['X-GitHub-Api-Version'] = '2022-11-28'
    data = body if isinstance(body, bytes) else None if body is None else json.dumps(body).encode()
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise SafeError('http_' + str(error.code)) from None
    except Exception:
        raise SafeError('transport_or_invalid_response') from None


def cf(path, method='GET', body=None, content_type='application/json'):
    _, data = request(CF_ROOT + path, method, body, os.environ['CLOUDFLARE_API_TOKEN'], content_type)
    if not data.get('success'):
        raise SafeError('cloudflare_api_rejected')
    return data.get('result')


def gh(path):
    return request(GH_ROOT + path, token=os.environ['SCHEDULER_GITHUB_TOKEN'])[1]


def runs():
    result = gh(f'repos/{REPO}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=100')
    if not isinstance(result.get('workflow_runs'), list):
        raise SafeError('invalid_github_run_list')
    return result['workflow_runs']


def audit():
    if not REPORT['cloudflare_token_secret_present']:
        raise SafeError('missing_CLOUDFLARE_API_TOKEN')
    if cf('user/tokens/verify').get('status') != 'active':
        raise SafeError('cloudflare_token_inactive')
    accounts = cf('accounts?per_page=50')
    selected = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    if selected:
        accounts = [a for a in accounts if a['id'] == selected]
    if len(accounts) != 1:
        raise SafeError('cloudflare_account_selection_required')
    prefix = 'accounts/' + accounts[0]['id'] + '/'
    scripts = cf(prefix + 'workers/scripts')
    existing = next((s for s in scripts if s['id'] == NAME), None)
    REPORT.update(cloudflare_authenticated=True, scheduler_already_exists=existing is not None)
    if REPORT['github_token_secret_present']:
        if not os.environ['SCHEDULER_GITHUB_TOKEN'].startswith('github_pat_'):
            raise SafeError('requires_fine_grained_github_token')
        if gh('user').get('login') != 'Yono24-jpg':
            raise SafeError('github_token_account_mismatch')
        workflow = gh(f'repos/{REPO}/actions/workflows/{WORKFLOW}')
        if workflow.get('path') != '.github/workflows/screen.yml' or workflow.get('state') != 'active':
            raise SafeError('scanner_workflow_identity_or_state_failed')
        REPORT['github_read_preflight'] = 'verified'
    REPORT['status'] = 'credentials_ready' if REPORT['github_token_secret_present'] else 'blocked_missing_SCHEDULER_GITHUB_TOKEN'
    return prefix, existing


def deploy(prefix, existing):
    if not REPORT['github_token_secret_present']:
        raise SafeError('missing_SCHEDULER_GITHUB_TOKEN')
    subdomain = cf(prefix + 'workers/subdomain').get('subdomain')
    if not subdomain:
        raise SafeError('workers_subdomain_not_registered')
    migrations = {'new_tag': 'v1', 'new_sqlite_classes': ['SchedulerCoordinator']}
    if existing:
        settings = cf(prefix + f'workers/scripts/{NAME}/settings')
        bindings = settings.get('bindings', [])
        expected = next((b for b in bindings if b.get('name') == 'SCHEDULER_LOCK' and
                         b.get('type') == 'durable_object_namespace' and b.get('class_name') == 'SchedulerCoordinator'), None)
        if existing.get('migration_tag') != 'v1' or not expected:
            raise SafeError('existing_scheduler_requires_migration_review')
        migrations = None
    before = {r['id'] for r in runs()}
    admin = secrets.token_urlsafe(40)
    metadata = {'main_module': 'worker.mjs', 'compatibility_date': '2026-11-08',
                'observability': {'enabled': True}, 'bindings': [
        {'type': 'secret_text', 'name': 'GITHUB_TOKEN', 'text': os.environ['SCHEDULER_GITHUB_TOKEN']},
        {'type': 'secret_text', 'name': 'SCHEDULER_ADMIN_TOKEN', 'text': admin},
        {'type': 'plain_text', 'name': 'SCHEDULER_ENABLED', 'text': 'true'},
        {'type': 'durable_object_namespace', 'name': 'SCHEDULER_LOCK', 'class_name': 'SchedulerCoordinator'}]}
    if migrations:
        metadata['migrations'] = migrations
    boundary = '----scheduler-' + secrets.token_hex(16)
    pieces = []
    for filename, kind, data in [('metadata', 'application/json', json.dumps(metadata)),
                                 ('worker.mjs', 'application/javascript+module', (HERE / 'worker.mjs').read_text())]:
        pieces.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{filename}"; filename="{filename}"\r\n'
                       f'Content-Type: {kind}\r\n\r\n{data}\r\n').encode())
    payload = b''.join(pieces) + f'--{boundary}--\r\n'.encode()
    deployed = time.time()
    cf(prefix + f'workers/scripts/{NAME}', 'PUT', payload, 'multipart/form-data; boundary=' + boundary)
    cf(prefix + f'workers/scripts/{NAME}/subdomain', 'POST', {'enabled': True, 'previews_enabled': False})
    url = f'https://{NAME}.{subdomain}.workers.dev'
    REPORT.update(worker_uploaded=True, url=url, status='uploaded_not_yet_verified')
    for _ in range(18):
        try:
            health = request(url + '/health')[1]
            if health.get('service') == NAME and health.get('configured') and health.get('enabled'):
                request(url + '/admin/status', token=admin)
                break
        except SafeError:
            pass
        time.sleep(5)
    else:
        raise SafeError('worker_health_or_secret_propagation_failed')
    cf(prefix + f'workers/scripts/{NAME}/schedules', 'PUT', [{'cron': '*/5 * * * *'}])
    schedules = cf(prefix + f'workers/scripts/{NAME}/schedules')
    if [s.get('cron') for s in schedules.get('schedules', [])] != ['*/5 * * * *']:
        raise SafeError('cron_configuration_not_verified')
    REPORT['cron_configured'] = '*/5 * * * *'
    # Concurrent real requests exercise the same durable claim as cron, with no force bypass.
    def tick(_):
        return request(url + '/admin/tick', 'POST', {}, admin)[1]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(tick, range(2)))
    if sum(r.get('outcome') == 'dispatch_accepted' for r in results) > 1:
        raise SafeError('duplicate_dispatch_detected')
    if not any(r.get('outcome') in ('duplicate_slot', 'dispatch_cooldown') for r in results):
        raise SafeError('durable_duplicate_guard_not_observed')
    REPORT['concurrent_test'] = results
    print('SCHEDULER_DEPLOYED ' + json.dumps(REPORT), flush=True)
    # Configuration alone is not cron evidence. Propagation can take several minutes.
    for attempt in range(80):
        state = request(url + '/admin/status', token=admin)[1]
        history = [h for h in state.get('history', []) if h.get('at', 0) >= deployed * 1000]
        cron = [h for h in history if h.get('origin') == 'cron' and h.get('outcome') in
                ('dispatch_accepted', 'scanner_already_active', 'recent_scanner_run', 'dispatch_cooldown')]
        accepted = [h for h in history if h.get('outcome') == 'dispatch_accepted']
        if any(h.get('outcome') == 'dispatch_rejected' or
               h.get('outcome') in ('workflow_check_failed', 'run_check_failed') and h.get('http_status') in (401, 403)
               for h in history):
            raise SafeError('github_token_permission_or_expiry_failed')
        if cron:
            REPORT['real_cron'] = cron[0]
        if accepted:
            first_dispatch = min(h['dispatch_at'] for h in accepted) / 1000
            observed = [r for r in runs() if r['id'] not in before and r.get('event') == 'workflow_dispatch' and
                        r.get('head_branch') == 'main' and r.get('path') == '.github/workflows/screen.yml' and
                        dt.datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).timestamp() >= first_dispatch - 10]
            REPORT['observed_runs'] = [{k: r.get(k) for k in ('id', 'html_url', 'event', 'status', 'conclusion', 'created_at')} for r in observed]
            if cron and any(r.get('conclusion') == 'success' for r in observed):
                REPORT['status'] = 'verified_real_cron_dispatch_and_scanner_success'
                return
        print('SCHEDULER_VERIFY_WAIT ' + json.dumps({'attempt': attempt + 1, 'cron_seen': bool(cron),
                                                   'accepted_seen': bool(accepted)}), flush=True)
        time.sleep(15)
    raise SafeError('deployed_but_cron_dispatch_or_success_not_yet_verified')


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else 'audit'
    if mode not in ('audit', 'deploy'):
        raise SafeError('invalid_mode')
    REPORT['mode'] = mode
    prefix, existing = audit()
    if mode == 'deploy':
        deploy(prefix, existing)


if __name__ == '__main__':
    code = 0
    try:
        main()
    except SafeError as error:
        REPORT.update(status='blocked_or_failed', error=str(error))
        code = 1
    except Exception:
        REPORT.update(status='blocked_or_failed', error='unexpected_deployment_error')
        code = 1
    (HERE / 'reports').mkdir(exist_ok=True)
    (HERE / 'reports/deployment.json').write_text(json.dumps(REPORT, indent=2))
    print('SCHEDULER_RESULT ' + json.dumps(REPORT), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write('```json\n' + json.dumps(REPORT, indent=2) + '\n```\n')
    raise SystemExit(code)
