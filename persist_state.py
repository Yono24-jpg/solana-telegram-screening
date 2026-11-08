"""Commit only state.json against the latest main, without resetting source files."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from state_store import merge


def git(*args, env=None, data=None):
    return subprocess.check_output(['git', *args], input=data, text=True, env=env, stderr=subprocess.DEVNULL).strip()


def persist():
    path = Path('state.json')
    if not path.exists(): return {}
    local = json.loads(path.read_text())
    for _ in range(5):
        git('fetch', 'origin', 'main')
        parent = git('rev-parse', 'origin/main')
        remote = json.loads(git('show', parent+':state.json'))
        merged = merge(remote, local, time.time())
        text = json.dumps(merged, sort_keys=True)
        if merged == remote:
            path.write_text(text); return merged
        with tempfile.TemporaryDirectory(prefix='scanner-state-') as tmp:
            env = dict(os.environ, GIT_INDEX_FILE=tmp+'/index',
                       GIT_AUTHOR_NAME='solana-screening-bot', GIT_AUTHOR_EMAIL='solana-screening-bot@users.noreply.github.com',
                       GIT_COMMITTER_NAME='solana-screening-bot', GIT_COMMITTER_EMAIL='solana-screening-bot@users.noreply.github.com')
            git('read-tree', parent, env=env)
            blob = git('hash-object', '-w', '--stdin', data=text)
            git('update-index', '--add', '--cacheinfo', '100644', blob, 'state.json', env=env)
            tree = git('write-tree', env=env)
            commit = git('commit-tree', tree, '-p', parent, '-m', 'Persist screening v2 evidence and delivery state', env=env)
            try:
                git('push', 'origin', commit+':refs/heads/main')
                path.write_text(text); print('STATE_PERSIST_OK'); return merged
            except subprocess.CalledProcessError:
                continue
    raise RuntimeError('state_persistence_failed')


if __name__ == '__main__':
    try: persist()
    except Exception:
        print('STATE_PERSIST_FAILED'); raise SystemExit(1)
