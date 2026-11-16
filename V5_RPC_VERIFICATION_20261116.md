# MAIL Hunter v5 — production RPC verification, 16 November 2026, 18:57 WIT

[PR18](https://github.com/Yono24-jpg/solana-telegram-screening/pull/18) merged as `eb41e6c930c56a957cda23d64943fa063af829b9`. Existing bot and scheduler retained.

RPC now applies a persistent 60-second cooldown to recognized transient JSON-RPC errors returned with HTTP 200, tries the next approved source on empty/partial account results, and fails closed when sources are exhausted. Raw provider error messages/data are never retained. Existing Helius URL configuration is reported accurately. Read-only method allowlist remains enforced.

[Integration](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43844226781): **256 Python + 30 scheduler/runtime + 28 legacy web = 314 passed, 0 failed**. [Production](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43844429425) success, repeated 256 Python regressions, getMe/getChat success, STATE_PERSIST_OK.

Production: **268 pools; 0 alerts**. Jupiter recovered 20 circulating-cap fields; 2 independently evidenced valuation conflicts rejected. Hydration: 144 incomplete before/after, 0 complete recoveries. These are separate metrics. NARRATIVE WATCH 300 retained records (bounded store; not 300 new candidates), VERIFIED ALERT 0. Health six-hour reservation remains not_due; scanner stays ON.

## Current source limitations

Pipeline operational, health **degraded**. Gecko hydration provider_backoff remains; latest rotating news reads returned unavailable for seven locale/category queries. Still-fresh prior news remains usable without renewing its timestamps. These failures are not changed to green. Public RugCheck and configured Solana RPC succeeded during the independent six-token audit; production did not reach a security candidate in this round. Helius/Birdeye keys and X bearer absent. X reads remain disabled.

Helius and Birdeye adapters activate only with owner-supplied official access. X requires `X_BEARER_TOKEN` with official read entitlement plus `X_READS_ENABLED=1`; profile URL observations are not image-content analysis. No paid package was bought.

## Dynamic trending-token audit

Jupiter returned 30 ranked tokens; six selected dynamically, with exact CA/pair/time evidence in the JSON report. Ranking is not proof of organic virality or official affiliation.

| Token | Market gate | Independent security evidence |
|---|---|---|
| MIHAO | Market cap outside bounds | RugCheck insider/bundle network detected (37 members reported) |
| ZEC (Solana mint in JSON) | Market-cap conflict | Mint authority active |
| TTWO | Market-cap conflict | Mint authority active |
| YzY | Pool age outside bounds | Insider coverage unavailable |
| PEAK | One-hour volume below threshold | Insider/bundle network detected (620 members reported) |
| OMNI | One-hour volume below threshold | Insider/bundle network detected (33 members reported) |

All six rejected; none completed every trade/holder/funding/security gate. Metadata-only Token-2022 extension passes are not complete safety clearance. Network findings are conservative provider-based screening reasons, not fraud allegations.

## Historical filter decision

Current production memory: 202 market-cap rejects and 15 age rejects, zero observed 24h samples and zero complete initial-safety records in both cohorts. Original cap/age archived for 133 and 6 respectively. No valid missed-safe-opportunity or historical-return conclusion. **Filters unchanged.** Old missing evaluation samples are not reconstructed using later prices.

## Cloudflare CI permission blocker

[Fresh official CI audit](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43844226849): secret present, expected account matches, user-token verification200; account-list403; scheduler settings/cron/KV401. Audit job success means diagnosis completed, not access restored.

Connected API still reads scheduler settings, five-minute cron, and 100% active version `aff5f5f0-79e3-480f-86fb-06e66928dd0c`. Official token-permission endpoint again returns403: connection lacks `account-api-tokens.write`. No token minted or secret replaced.

Owner action required: create a properly scoped token for the existing account through [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens), then replace `CLOUDFLARE_API_TOKEN` directly in [repository Actions secrets](https://github.com/Yono24-jpg/solana-telegram-screening/settings/secrets/actions). Existing deployment scripts need Account Settings Read, Workers Scripts Edit and Workers KV Storage Edit on the correct account. Keep values out of chat. Then rerun official access audit before deployment. Account and user token verification endpoints differ; these scripts currently verify user tokens.

No Cloudflare Worker code changed; Python scanner release runs through main/Actions. Original scheduler cron, ON/OFF and six-hour health logic retained. No synthetic signals, secret disclosure, signing or auto trading.

Research internal_only means no Telegram notification; this existing repository/state is public. Structured evidence: [audit/rpc-verification-20261116.json](audit/rpc-verification-20261116.json).
