# MAIL AI Narrative Hunter v5.1 — Free Intelligence

Existing repository, @SolHawkHunter917Bot and mail-solana-scheduler retained. No paid plan, signing or auto trading. This is an engineering release, not proof of profitable trading or exhaustive intelligence.

## Changes deployed

- Revalidate independent circulating-cap evidence before choosing a coherent DEX/Gecko snapshot. Preserve only exact-mint, fresh positive circulating cap whose price*supply is consistent and whose token price agrees with the selected pool. Do not combine pool liquidity, volume or transaction counts. Valuation-conflict flags are sticky.
- Retry incomplete pools in rotation within age/liquidity priorities. Persist up to 300 retry timestamps so the same first 40 pools do not monopolize every cycle.
- Submit newest-pool page first and run initial pool discovery before evaluator/news work. Feed the fetched quotes into early evaluation to avoid repeated quote requests. Five-minute polling and source indexing latency still limit discovery.
- Apply Birdeye after hydration and existing-watchlist refresh. Spend on otherwise useful cap-only-missing pools, rather than multi-missing large-liquidity tokens. Keep the 24,000 CU rolling31-day ceiling, daily/hourly caps, cache and one-second rate policy. Helius quota limits/cache remain; added transaction-pattern checks reuse fetched finalized transactions.
- Refresh game, AI and anime/donghua priority news alongside six rotating locales. Record region coverage and recent article observations. These are news observations, not verified social virality.
- Reject a creator co-signing any sampled wallet trade and three sampled wallets buying and selling within finalized five-minute swaps. These are conservative risk indicators, not fraud allegations. Mandatory mint/holder/LP/insider/funding/sell/Token-2022 gates remain.
- Force X_READS_ENABLED=0 in the production workflow and scanner. Key presence does not enable paid X calls. Regression verifies no X network request even when a saved variable attempts to enable it.

## First production proof

[PR24](https://github.com/Yono24-jpg/solana-telegram-screening/pull/24), merge 98c705bdf59e2847121e01a9b7e208600ede8945.
[Integration 43886185587](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43886185587): 278 Python +30 scheduler/runtime +28 legacy web =336 tests passed.
[Production 43886438189](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43886438189): success, version5.1, 291 pools,0alerts. Initial discovery began0.123s into scan and finished0.984s later, with44pools younger than1h. This was the pre-Gecko-pacing release; it is not the final paced discovery duration.
- Initial Jupiter enrichment recovered23 cap fields; post-hydration Jupiter recovered0.
- Hydration151 incomplete before/after; final151 incomplete. No complete snapshot restored and no cap-proof preservation event observed in this population. Proof preservation is tested adversarially; do not claim it ran on a live candidate when its counter is0.
- Birdeye eligible cap targets0, new calls0, local estimated ledger132CU. Endpoint success timestamps remain historic and are not represented as new calls.
- Helius successful finalized-slot probe. X bearer configured=true, reads_enabled=false.
- getMe/getChat/getUpdates and STATE_PERSIST_OK; health not_due; existing ON/OFF and six-hour delivery state retained.
- No candidate reached final security checks on that cycle. New wallet detectors are regression-tested with adversarial finalized-transaction fixtures; not claimed to have caught a live rug pull.
- Health degraded for Gecko hydration backoff and incomplete mandatory market fields. Missing counts overlap: priceChange.m5=131, liquidity47, cap17, price5.

Baseline 43883921419:335pools,164incomplete; no hydration recovery. Different populations/times mean fewer incomplete pools is not controlled proof of better coverage or returns.

## Gecko follow-up

Official public documentation https://api.geckoterminal.com/docs/index.html describes approximately10calls/minute and one-minute server caching; other official help pages mention30/minute. The conservative limit is used.
[PR25](https://github.com/Yono24-jpg/solana-telegram-screening/pull/25) serializes v5.1 Gecko calls at least6.2s after response completion, retaining the nine-request rolling-minute budget and bounded Retry-After backoff. Completion timestamp survives state merge. Requests already in backoff return immediately; waits that would exhaust scan budget are refused. Legacy scanner defaults are retained.
The newest-feed response arrival is recorded separately from completion of all discovery sources. Pacing trades burst speed for source availability and does not guarantee no shared-IP/provider429.

## Limits retained

Unknown pool data is never zero-filled or replaced with token-wide volume/liquidity. Price/supply evidence must be fresh; FDV/total supply is not relabelled circulating cap. All security and market thresholds remain unchanged. Helius/Birdeye integrations remain configured; RugCheck/public Solana RPC/DEX paths remain. No new paid APIs activated.

X posts, influencer identity and profile-image changes remain unavailable through X while paid reads are OFF. Public Bluesky feed samples and multilingual news offer limited leads only. No full influencer, image/video, insider graph or whale identity coverage is claimed. Large-trade USD values remain provider-reported unless independently proven; transfer data alone is not a whale purchase.

Cloudflare connected API verifies enabled scheduler, cron */5 * * * *, original AI/secret/Durable Object bindings and active Worker version aff5f5f0-79e3-480f-86fb-06e66928dd0c (100%traffic). Worker code did not change; scanner release runs through main/GitHub Actions. This does not claim the previously restricted CI Cloudflare token was repaired.

Final paced-production evidence is appended below. Structured data: [audit/free-intelligence-v51-20261116.json](audit/free-intelligence-v51-20261116.json).

## Final paced release verified — 23:36 WIT

[PR25](https://github.com/Yono24-jpg/solana-telegram-screening/pull/25) merged as 47ad7434bb52bdff06c6f460c4a100daf5470366.
[Final integration 43887045027](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43887045027): **279 Python + 30 scheduler/runtime + 28 legacy web = 337 passed, 0 failed**.
Read-only live audit: 305 pools; all discovery feeds responded; newest feed arrived0.104s after discovery started, whole paced discovery stage25.301s. Hydration recovered1complete snapshot,161→160incomplete, by restoring missing m5 change in a coherent snapshot. Gecko later entered backoff during hydration. This is a source observation, not evidence pacing eliminates all429s.

[Final production 43887437844](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43887437844) completed success on final version5.1. Repeated279 Python regressions. getMe/getChat/getUpdates and STATE_PERSIST_OK succeed; health not_due.

| Final production metric | Value |
|---|---:|
| Pools examined | 228 |
| Pools younger than1h in available discovery | 9 |
| Initial Jupiter cap fields recovered | 3 |
| Additional post-hydration cap recovery | 0 |
| Complete snapshots recovered in this production cycle | 0 |
| Remaining incomplete pools | 134 |
| Birdeye eligible cap targets / new calls / new CU | 0 / 0 / 0 |
| Birdeye estimated persisted31day CU | 132 |
| Candidate alerts | 0 |

Final production used DEX sources while Gecko was already in persisted provider backoff. Newest Gecko arrival is null; the0.125s initial-discovery duration is therefore **DEX-only availability**, not a successful Gecko retrieval or total token-detection latency. The paced network path was exercised in live CI; this final production cycle verifies the backoff path and release, not a new successful Gecko network request.

Helius successful finalized-slot probe and Jupiter reads. X bearer configured=true, reads_enabled=false. Birdeye remains configured with prior successful endpoint timestamps; no new calls were made and its old successes are not described as fresh usage. All final-security checks were skipped because no pool reached eligibility; new anti-wash/developer checks were validated adversarially.

Final health is **degraded** for missing mandatory pool data and Gecko backoff. Missing-field counts overlap: m5priceChange127, liquidity45, cap7, price5. Different pool populations make comparison to earlier incomplete counts non-causal. The three cap fields are not three recovered complete snapshots. No safe-opportunity rate or profit uplift is claimed.

All authorized software changes have been tested and deployed. Upstream fields not supplied by free sources, public provider throttling and intentionally disabled X access remain limitations. They are not bypassed, fabricated or cosmetically hidden.
