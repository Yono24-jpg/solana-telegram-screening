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
