# MAIL Hunter v5 — official data intelligence

Existing repository/bot/dispatcher; ALERT ONLY. No provider subscription purchased, no signing or execution endpoint added.

## Access and integration

- Jupiter `api.jup.ag/tokens/v2/toptrending/5m` and `/search`: official keyless reads tested. Optional `JUPITER_API_KEY` header, minimum2.1s between requests,4 calls/cycle and1000/day local ceiling. Dynamic top30 seeds resolve to exact-CA DEX pools. A token aggregate is never treated as a pool snapshot.
- Jupiter cap fallback requires exact mint, `circSupply` (not total supply), consistent positive mcap/price*supply within2%, timestamp <=120s and agreement with the pool price within10%. FDV cannot substitute. Final quotes revalidate the evidence.
- Helius standard Solana mainnet RPC activates only with `HELIUS_API_KEY` or the existing configured Helius RPC URL. Failed/empty JSON-RPC results fall back to the existing configured endpoint and the official public mainnet endpoint. Read-method allowlist rejects all transaction-sending methods. No paid parsed-events product is activated.
- Birdeye `/defi/token_overview` support uses owner-supplied `BIRDEYE_API_KEY`, exact address validation, max2 corroborating reads/cycle. Without a key it is explicitly not_configured. Token overview never replaces pool liquidity, transactions or safety proofs. Keyless probe returned401.
- RugCheck public summary/full reports are integrated with bounded calls and circuit breaker. Optional JWT `RUGCHECK_BEARER_TOKEN` uses Authorization. No forced refresh/paid bulk/token-verification endpoint. Full reports still require exact mint, pool, program, supply, LP lock and explicit insider coverage.
- All provider failures emit fixed status codes, never URLs/credentials.401/403 backoff1h;429 Retry-After60–900s; per-cycle/day quota; persistent circuit state. Existing Gecko and DEX/CoinGecko fallback remains.

## Research and notification tiers

NARRATIVE WATCH requires source-backed narrative but can retain market/security rejections. Bounded300 entries/7days, internal state and Actions artifact only, never Telegram. VERIFIED ALERT requires the existing entire base/holder/LP/insider/developer/funding/swap/sell/Token-2022 and final-market/narrative checks. Existing durable GLOBAL SIGNAL suppression retained across the label change; risks remain in the message. Watch classification alone cannot invoke delivery.

## Safety and social scope

Token-2022 keeps conservative allowlist and rejects executable/unverified mint accounts; all unsupported/unknown extensions reject. Existing creator/shared-funder, bundling, wash and holder checks remain. Creator co-signing a sampled buyer transaction additionally rejects. Large trades are listed only from finalized verified swap samples; their USD values remain provider-reported and wallet identity is not asserted.

X uses only a configured official bearer token AND existing owner-enabled `X_READS_ENABLED=1`. Profile lookup requests profile_image_url; repeated observations detect URL changes and exact contract-post IDs, not image contents. No X key means no influencer/post access claim. Authorized X product/read entitlement is needed; no paid access enabled. Bluesky continues its explicitly limited public-author-feed fallback.

Health separates pipeline operation, source failures and optional coverage. Valid `no_recent_articles` no longer means an outage; actual source errors still produce degraded. Missing Helius/Birdeye/X access remains partial coverage, not invented data.6h health now includes incomplete data and internal-watch counts.5m cron/ON-OFF preserved.

## Historical filter review

Original cap/age are now archived at first observation. Historic cap/age rejects are summarized only with actual forward samples and original safety coverage. Existing archives lack adequate predecision safety/24h evidence; no safe missed-opportunity/win-rate claim and no threshold changes. Current trending audits are live observations, not historic backtests.

## Cloudflare CI403

Official account/user token-permission endpoints return403 to the current connection; user-token endpoint explicitly says OAuth cannot grant that operation. Connected Workers reads still work. Browser fallback reached Cloudflare sign-in with no authenticated session. No token can be silently minted, extracted, or installed; CI secret403 is not claimed fixed. A properly scoped replacement must be created by the authorized owner and stored directly in GitHub Actions secrets. Never paste it into chat. No existing Worker is replaced to bypass this blocker.

## Sources

https://github.com/jup-ag/docs/blob/main/tokens/index.mdx
https://github.com/jup-ag/docs/blob/main/tokens/token-information.mdx
https://developers.jup.ag/changelog/developer-platform
https://birdeye.so/data-api/changelog
https://api.rugcheck.xyz/swagger/doc.json
https://www.helius.dev/docs
https://solana.com/docs/rpc/http

CI, live token cases and production evidence are appended after verification.

## Additional diagnosis and safety checks

Direct CI diagnosis43826836202: existing secret present; user-token verify200; account list403; scheduler settings/cron/KV metadata401 on the known existing account. The token is authenticated but cannot access the required account resources. This is not fixed by omitting account enumeration or suppressing a failure. A correctly scoped account/resource token must replace the CI secret through an authorized secret-management path.

Independent fresh Jupiter circulating-cap evidence differing >20% from a positive pool-provider cap now marks valuationConflict; all hunter modes reject v5_market_cap_conflict. The convenient lower cap is not selected. It requires matching CA, recent timestamp, circulating supply consistency and pool-price agreement before declaring a cap conflict.

Integration evidence before final merge: live audit saw356 pools,13 caps recovered; subsequent333 pools,14 recovered,5 valuation conflicts blocked. Internal source-backed watch106–108,0 verified alerts. Actual source failures and partial access remain visible. These are different live populations, not a controlled performance comparison.

## Final verified production — 17:01 WIT

[PR16](https://github.com/Yono24-jpg/solana-telegram-screening/pull/16) and [PR17](https://github.com/Yono24-jpg/solana-telegram-screening/pull/17) merged. Final scanner merge `bc584f04af7304aa86e426c1379f664c196a4670`.

[Final integration43827705831](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43827705831):252 Python +30 Workers/runtime +28 legacy web = **310 passed,0 failed**. [Production43827883091](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43827883091) succeeds;252 Python regressions repeat; getMe confirms original bot, channel verified, STATE_PERSIST_OK. ON/OFF stays ON, health6h not_due; existing health message408 retained. No artificial Telegram alert.

| Operational observation | Before43826700270 | Final43827883091 |
|---|---:|---:|
| Pools |334|288|
| New Jupiter circulating caps |0|16|
| Additional full hydration recoveries |0|2 (160→158 incomplete)|
| Independently evidenced cap conflicts rejected |not implemented|4|
| Explicit internal NARRATIVE WATCH |not implemented|172|
| VERIFIED ALERT / Telegram candidates |0|0|
| Overall health |degraded|degraded (Gecko provider_backoff)|

Jupiter enrichment precedes legacy hydration, so16 recovered cap fields and2 additional complete snapshots are different metrics and must not be added as18 fully recovered pools. Populations/time differ, so this comparison does not prove improved opportunity capture or returns. Remaining missing fields overlap:priceChange.m5=121,liquidity69,marketCap47,price17,creation3. No zero fill.

Final provider status confirms Jupiter/public RugCheck/configured Solana RPC success. Specific Helius and Birdeye keys absent; X key absent/disabled. All three stay explicitly inactive. Coverage partial. Final5m observations104/missed135;15m97/missed116;1h145/missed2;24h0. No reconstruction of old missed samples.

Source-health follow-up deliberately includes hydration failures: first production43827273483 showed discovery operational even while hydration returned429; PR17 prevents this from being reported as fully healthy. Current pipeline operational plus health degraded is intentional evidence, not a cosmetic green status.

### Actual trending-token examples

All candidates below were rejected; exact mint/pair/timestamps and report fields are in `audit/data-intelligence-20261116.json`. Trending means Jupiter ranking, not verified organic spread. Low provider scores do not bypass network risks.

| Token and audit round | Market/narrative finding | Independent security finding |
|---|---|---|
| Marvin The Martian (first/third audit) |weak_activity; narrative_unverified|RugCheck reported37 insiders/network members; insider_or_bundle_network_detected; metadata-only Token-2022 extension audit passed, not full security|
| WIGGLES (first audit) |weak_activity; narrative_unverified|RugCheck reported55 insiders/network members; rejected despite low normalized score1|
| TTWO (subsequent audit) |v5_market_cap_conflict|mint authority active; stock-like token is not presumed an official meme narrative|
| NVDA (subsequent audit) |v5_market_cap_conflict|mint authority active|
| NIO and greg (final audit) |weak_activity|insider_or_bundle_network_detected|
| HYPE (final audit) |v5_pool_age|report_authority_active_or_unknown|

These are screening decisions, not assertions a token is fraudulent. No token is declared fully safe or able to sell merely from a mint-extension pass. First production also exercised a live metadata-only Token-2022 mint that passed base checks but was rejected wash_sample_risky_or_incomplete before alerting.

Historical cap/age review found no adequate original-safety/24h sample to validate alternative bounds. Filters unchanged; opportunity-cost profitability unvalidated. Original cap/age now archived prospectively. Research storage is bounded; internal-only refers to notification behavior, not private storage: this existing repository/state is public.

Cloudflare connected API re-verifies unchanged5m cron and active Worker version; main Python code is deployed through Actions, so no replacement Worker/bot. Telemetry16:41/16:46/16:51WIT accepted dispatch204;16:56WIT correctly suppressed an already-active production scan. Full structured proof includes the final source status and CI scope diagnosis. The CI-token issue remains blocked: official read-only audit returned verify200, account-list403, targeted scheduler/KV401. Owner-authorized replacement must be scoped to the actual account and entered directly in GitHub Actions secrets; never in chat. No all-access-restored claim.
