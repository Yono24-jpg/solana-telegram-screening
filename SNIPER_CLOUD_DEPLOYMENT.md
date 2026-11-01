# Solana AI Sniper — cloud PAPER ONLY

Status: prepared, not deployed. No proof of 24 hours of cloud availability yet.

This is the existing project in `/workspace/scratch/646dcb859165/`. The six engine modules and the 102-test baseline have not been changed. `sniper_cloud_worker.py` only supplies process supervision, ON/OFF controls, durable operational records, and a 24-hour entry window around the existing engine.

## Runtime

- Python 3.12, standard library only. `python -u sniper_cloud_worker.py`.
- One service process; a cross-process file lock rejects a second worker on the same persistent disk.
- The HTTP control server and the paper worker run in the same service. This uses a paid **web service** because a Render background worker has no inbound URL for the ON/OFF page.
- Persistent directory `/var/data/sniper/`; SQLite stores positions, pair pins, seen mints, discovery/history cursors, ON/OFF and deadline, process starts/stops, and round summaries.
- `sniper_cloud_seed.json` is a validated export of the existing paper state, with 0 positions, 0 seen mints and $0 PnL at packaging. It is imported only when the durable database does not exist. Existing state is never replaced on restart. Historical market audit files remain in the original project; historical caches are not published in the Git deployment source.
- `latest_round.json.gz` retains the most recent complete raw round; compact summaries remain in SQLite. No ever-growing in-memory list of all rounds/requests: the same rate-limited Reader is reused and request logs reset after each persisted round.
- SIGTERM stops new entries, saves completed work, and closes SQLite. A hard stop relies on the existing SQLite WAL/FULL transaction recovery. The platform restarts the process. Disk-backed Render redeploys have an interruption; this is not zero-downtime execution.

## Strategy and controls

PAPER_ONLY=1 and REAL_TRADING=OFF are mandatory. There is no wallet connection, signing dependency, private-key input or transaction submission endpoint. Unknown security data remains rejected. All existing market, finalized age, extension and route filters are retained.

BUY $5, TP +20%, SL −10%, maximum two positions. Modeled costs remain 1.3% plus $0.05 per side and 50 bps adverse slippage per side; these are assumptions, not measured execution costs. A paper BUY debits $5.115 and slippage reduces the token quantity.

The root page provides ON and OFF plus a read-only result display. It requires a separate generated control token for authenticated API calls; this token has no wallet authority. It must be retrieved through the deployment provider's secret configuration, never posted publicly or committed. HTTPS is provided by the platform. Authorization headers are not logged and the token is not saved in browser storage.

- `POST /api/on` allows paper entries only after all existing filters pass.
- `POST /api/off` blocks new entries, including a final BUY decision already being evaluated. It pauses subsequent discovery rounds. Existing positions continue being monitored for simulated exits.
- `GET /api/report` returns results, costs, positions, session deadline and process/round records; authentication required.
- `GET /healthz` exposes only mode and worker liveness.

First ON begins a 24-hour entry window. OFF/ON or restart cannot reset that deadline. After expiry, no new BUY is allowed; remaining positions continue to be monitored and are not forcibly sold. This does **not** stop cloud billing or delete the service. Round duration depends on public API latency and strict verification; there is no sub-second exit guarantee. Public RPC access can return errors/429; the existing shared caps of 20 RPC reads/minute and 30 market GETs/minute remain enforced.

## Hosting decision

Official Render documentation checked on 1 November 2026:

- https://render.com/docs/free : free web services spin down after 15 idle minutes, lose local SQLite on restart and cannot attach a persistent disk. Background workers have no free instance. A free Postgres database expires after 30 days, and changing the existing SQLite engine to Postgres is outside this targeted deployment.
- https://render.com/docs/compute-plans : smallest always-on compute is 0.5c-512mb (legacy Starter).
- https://render.com/pricing : $7/month compute plus $0.25/GB/month persistent disk; selected 1GB totals approximately $7.25/month before taxes, bandwidth/build overages or other account charges.
- https://render.com/docs/disks : only data under the mount survives restart; one disk-backed service instance; disk disables zero-downtime deployment.
- https://render.com/docs/blueprint-spec : the draft `render.yaml` uses one paid web service with one disk, generated control secret, health check and 300-second graceful shutdown.

This is the single proposed deployment target. A free web service plus artificial keep-alive traffic is not used as a substitute for an always-on durable worker.

## Operational verification and release gate

102 existing tests remain the baseline. Only the new operational shell receives a small smoke check, `python sniper_cloud_operational_check.py`. Its synthetic trades are clearly labeled and cannot establish a real-market BUY→SELL cycle.

`sniper_cloud_live_check.py` launches the actual service locally, verifies health and authenticated ON/OFF, runs bounded read-only market observation, and records `sniper_cloud_live_operational.json`. It does not establish cloud uptime. `sniper_cloud_build_evidence.json` records unchanged engine hashes and public JSON-schema validation. Render CLI validation is not claimed because the CLI is unavailable.

Before declaring deployment operational, the deployment must reach `live`, return HTTP health, prove authenticated OFF/ON and restart recovery on the attached disk, and record fresh worker rounds from that cloud service. To prove 24h operation, compare provider deployment/events/logs and persisted process/round timestamps over the full period, explicitly reporting any gaps. The current report deliberately never infers 24h proof from a running process or successful build.

## Current deployment gate

Render account discovery succeeds. It contains `My Workspace` (`tea-dbidjjt9fdbs73c0kml0`), but no workspace is selected. The access tool explicitly requires the user to confirm the destination before resource operations. No paid resource has been created and no deployment has been triggered. One confirmation is required: use that workspace for the reviewed approximately $7.25/month deployment.

The existing GitHub repository is available with write access. Deployment source is prepared on a separate `solana-ai-sniper-paper` branch. The scanner's main branch, workflow, settings and secrets are not changed. Source publishing does not mean the cloud worker is running.
