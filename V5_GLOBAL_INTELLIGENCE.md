# MAIL AI Narrative Hunter v5.0

Existing bot/repository/Cloudflare dispatcher retained. ALERT ONLY; no signing key, order, or auto-trading path added. `bot.py` invokes `scanner_v5.run`; legacy scanners remain for rollback. ON/OFF remains administrator-only.

## Modes and shared gates

| Mode | Pool age | Actual market cap | Additional evidence |
|---|---|---|---|
| EARLY HUNTER | 1m–24h; prefer 1–60m | $20k–500k | Recent independently reported narrative |
| VIRAL HUNTER | 1m–90d | $20k–5m | Observed 5–15m volume >=1.5x, buys and transactions >=1.2x |
| PARODY HUNTER | 1m–90d | $20k–5m | Tentative spelling similarity to independently reported name |

Every mode: LP >=$10k, hourly volume >=$5k, 5m buy/sell >=1.5. Existing stricter protections retained: LP/MC >=8%, 5m volume >=$1.5k, buys >=12, price change 5m 0–25%, hourly -15–80%, 24h <=200%, no LP withdrawal >=10% between observations. Missing MC never uses FDV. Missing hourly/24h price windows reject. Pool identity/time conflicts reject. Mode membership never grants a security exception.

## Intelligence: implemented scope

- Seven bounded RSS requests per 10m; six rotating locales (US, China, Japan, Korea, Indonesia, Brazil), rotating game/AI/animal/influencer/screen/meme/company/breaking/exchange/CTO queries plus open news. This is sampled coverage, not exhaustive world monitoring. Cache retains article publication AND first observation times.
- Unicode entities and repeated headline names form emergent labels; names need two distinct publisher domains and differing headlines. No manual token name list required in production. Similarity is a hypothesis, not proof of association. Syndication and publisher ownership can still be imperfectly detected.
- 12 rotating dynamic DEX searches, including conservative name-prefix retrieval for spelling parodies; DEX feeds + Gecko trending/new pools; pool-matched hydration and bounded 90d watchlist. Advertisements/boosts/CTO feeds are leads, not endorsements.
- Optional Cloudflare Workers AI uses existing OIDC broker and existing AI binding. Exact model returned by provider is recorded. Max eight inferences/day, 3h cache, max30 headlines; deterministic extraction works without LLM. No GPT API subscription/key or paid social access assumed. Model output cannot override source or security gates.
- Public Bluesky AppView search: bounded samples of recent posts, CA mentions as untrusted discovery leads, authors/interactions, separately observed mention counts and avatar URL changes. Access errors are reported, not bypassed. Changing an avatar URL is not image-content recognition or a verified influencer event.
- Existing official X API reads only if both bearer token and owner enable flag already configured. Telegram metadata/public posts are sampled. Community score unknown unless both source scores exist. Member-count differences do not prove human users. Paid boosts may be observed; organic status stays unknown. No X/TikTok/Instagram firehose, image/video understanding or automatic influencer-account discovery claimed.
- Large provider-reported trades >=$10k are recorded with signature/wallet; no assertion that wallet belongs to an identifiable whale. Full on-chain trade safety sample is checked separately.

## Security

Finalized mint account, mint/freeze revocation; classic canonical layout; Token-2022 strict TLV structure. Only extension-free or immutable, self-referential, valid metadata-only (18/19) mints supported. Duplicate/truncated layouts, external/mutable metadata pointers, transfer fees/hooks/delegates/confidential/non-transferable/pausable/scaled/unknown and all other unsupported extensions reject. This is conservative extension auditing, not universal Token-2022 compatibility.

Existing strict full RugCheck report must bind mint/program/supply and exact pool, explicit empty insider networks plus consistent graph coverage, no critical/suspicious risks, normalized risk <40, >=95% locked LP with >=$10k locked. Unknown security data rejects. Program-owned vault proofs prevent arbitrary holder exclusions. Top10 token accounts <=30%, observed owner <=15%, developer holdings <=5%, bounded recent creator outflow checks. Recent sampled wash/repeated-size/roundtrip/concentration checks, >=20 observed buyer addresses, plus 12 buys/3 independently signed sells verified finalized against supported pool-swap instructions. Same-slot/shared-signer patterns reject. These are bounded snapshots, not proof that all wallets or future sells are safe.

## Scores, memory, evaluation

Six independent fields: narrative, virality, momentum, community, security, evidence quality. Unmeasured social virality/community are `null`; news attention is not social virality. Scores rank evidence, not profit probability.

- Durable first-writer delivery reservation before Telegram I/O; unknown response is not retried. One shared GLOBAL SIGNAL suppression across modes; previous signal entries suppress repeats. First-writer reservations also protect 6h health reports, including when scanner OFF. Health delivery errors are visible and suppressed for6h to avoid duplicates.
- At most1500 sampled decisions for90d,200 social samples,200 watched pools; capacities may evict before retention expires. Full current scan, memory, point-in-time and replay reports saved as Actions artifacts for14d. These bounds are not unlimited memory.
- Actual future observations at5m/15m/1h/24h, late/missing samples explicitly marked; no backdated prices, fees/slippage or executed-return claims. Rejections sampled up to30 per scan plus market candidates, one pool record per6h; this creates selection bias and cannot estimate market-wide win rates.
- Replay uses only article `published_at` AND `observed_at` <= decision time, chronological past price history and already observed security snapshots. No hindsight safety report substitution. Research case cards are not pre-pump training/backtest proof. Historic point-in-time market/social/security archives are not available for all requested cases; historical profitability remains unvalidated. No automatic threshold changes or model weight training.

## Scheduling and cost

Existing Cloudflare `*/5 * * * *` cron and durable dedup remain. Existing GitHub5m schedule fallback remains under shared Actions concurrency; dispatcher checks active/recent scanner before dispatch. Healthy health summaries every6h, no fabricated token alert to test Telegram. Free public endpoints are rate-limited and incomplete; candidates can be rejected or deferred on deadlines. AI quota limits preserve existing low-cost policy; no paid plan is activated.

## Verification

`python3 -m unittest -vb`; `npm ci && npm test` in scheduler; `node --test cloudflare/*.test.mjs`. Feature workflow additionally executes `v5_live_audit.py` with live public data but no Telegram token, no identity token, and no sending/persisting to production. Actual main workflow separately verifies OIDC AI, Telegram health and production scanner. Deployment evidence recorded after those runs complete.
