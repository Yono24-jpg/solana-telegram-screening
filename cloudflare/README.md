# Always-on Cloudflare momentum scanner

This is the existing separate Worker, updated in place. The original Python bot, its workflow and state file are unchanged. Cron runs every minute independently of Telegram controls or the phone. No wallet, trading, webhook or getUpdates consumer is installed.

## Market and momentum rules

Only pools aged 5–10 minutes may generate an initial candidate alert. Pools can be observed earlier to build a baseline. Required: complete market identity and metrics, liquidity >= $10,000, 5m volume >= $1,500, buys >= 12, sells >= 3, buy/sell >= 1.5, liquidity/market-cap >= 8%.

Comparison baseline: a recorded snapshot 2–8 minutes earlier for the same pool and mint. Missing baseline fails closed. 5m price momentum must be 0–80%, 1h momentum >= -15%, price since the baseline 0–40%, LP retention >= 90%. 5m volume must grow >= 1.1x, or sustain >= 0.9x with volume >= $10,000, buys >= 50, buy share >= 62% and liquidity >= $15,000. Buy count cannot fall below 90% of its baseline. The previous blanket rejection above +15% in 5m and +60% in 1h has been removed.

Score >= 70 combines buy pressure, rolling 5m volume growth, liquidity depth, buy activity and measured price extension. It is a transparent rule score, not an AI prediction, probability or validated return model. Thresholds are not fitted to a single historical winner. No return is promised.

## Required security remains unchanged

Mint and freeze authority disabled, standard mint or explicitly supported harmless Token-2022 extensions, top ten token accounts <=30% of supply, complete RugCheck summary with no danger/critical risks and normalized risk <60, and fresh complete market/momentum checks. Top ten token accounts are not unique wallets and can include liquidity vaults. A failed or unavailable security check never produces an initial alert. At most five ranked distinct mints are checked per run, subject to completing all checks within the request budget.

## Extra pool discovery

DexPaprika keyless pool search supplements existing sources. It is queried once every six minutes (<=7,200 calls in 30 days, before occasional deployment probes), aligned with KV checkpoints. Up to 50 pool addresses created in the last ten minutes and with reported liquidity >=$5,000 are cached, then refreshed through DEX Screener every scan. No DexPaprika price/volume/transaction figures are used to approve a candidate. HTTP 402 pauses this optional source for 30 days and HTTP 403 for one day; no payment or account is created. GeckoTerminal HTTP 429 stops further GeckoTerminal requests for that invocation. Source coverage remains sampled, not exhaustive.

## Delivery and measured results

Only after Telegram confirms an initial candidate message ID is its price, observation time, alert time and receipt added to performance records. Tracking uses the same pool and mint. Both increases and decreases are recorded, with the highest and lowest *sampled* price; these are not exact ATH/ATL or realised profit. Missing subsequent data is labelled unavailable, never extrapolated. There are no fabricated winner records.

Up to 40 latest confirmed alerts are tracked for 24 hours. At sampled +50% steps or -20% drawdown steps, the original message can be edited (at most two edits/run), showing current gain, sampled high/low, liquidity and update time. These are monitoring updates, not new buy signals, and do not claim a fresh security check. The latest 200 records are retained for up to seven days; untracked/expired records are labelled. Slippage, fees and execution are not included.

Public read-only `/data` displays recent observations with rejection reasons and actual receipt-backed performance records. Observations are not approved signals. `/health` reports the engine revision. Credentials and chat IDs are not included.

## Free limits and verification

History checkpoints every three minutes (480 writes/day), plus at most 200 delivery reservation writes and at most 200 extra receipt checkpoints/day, keep expected KV writes <=880/day. Initial alert attempts remain capped at 200/day. No uncertain initial delivery is automatically retried. KV is eventually consistent; strict cross-region exactly-once delivery is not guaranteed. Requests are capped at 34 externally so KV operations remain within the free invocation budget; incomplete checks are discarded. Provider rate limits can temporarily reduce discovery. Cron retries next minute rather than turning the bot off.

Deployment runs the original Python regression tests and Worker tests, sends an explicitly labelled real connection test (not a candidate alert), and waits for a real scheduled state tagged `momentum_v2.4`. Tests with synthetic fixtures do not establish market performance. An initial real candidate and subsequent price history are required before claiming successful token selection.

Provider HTTP 429 stops further calls to that host in the invocation. Retry-After is cached at the Cloudflare edge between KV checkpoints and saved with periodic state; unavailable data is never replaced with a fabricated value. This reduces repeated requests, but does not remove provider rate limits or promise complete coverage.

Optional repository secret `DEXPAPRIKA_API_KEY` is copied to a Worker secret binding. A registered free key enables one discovery call per minute (<=43,200/30d). The key is sent as the bare Authorization value only to api.dexpaprika.com; a response must identify x-api-plan=free, otherwise the source is rejected. Moving from keyless to an authorized free key clears the old IP-quota cooldown. Keyless discovery remains once/6m. No paid host or plan is used.

Free-plan labels are normalized for capitalization. A client-side unknown/keyless plan result retries after three minutes instead of locking the source for a day; existing client validation locks are migrated once. Actual HTTP 402 quota denials and 403 permissions retain their separate cooldowns. Sanitized provider plan/redirect/type/length metadata is available for diagnosis without exposing credentials.
