# Birdeye Standard verification — 16 November 2026

Existing MAIL AI Narrative Hunter v5 on Yono24-jpg/solana-telegram-screening. No new bot, paid plan, key disclosure or trading.

## Verified Standard access

[First metered production43879236344](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43879236344) success. Saved BIRDEYE_API_KEY used only in the request header. Both official endpoints returned success with the real key:
- GET /defi/price : price71.0908327894USD, token aggregate liquidity4326632162.169148USD, source update1794836877.
- GET /defi/token_overview : price71.1014378974USD, marketCap42069620220.683365USD, circulatingSupply591684520.9428837, liquidity4326632162.169148USD, v1hUSD94420863.53850216 and v24hUSD2030524262.146935.
- Exact mint: So11111111111111111111111111111111111111112. Observed22:47:58–22:47:59WIT. These are timestamped live probe values, not current quotes or a buy signal.
- Two calls reserved21CU. Persisted ledger93CU includes72CU conservatively imported from four known legacy overview attempts, not93new CU spent in that cycle. Both endpoint statuses and cache entries were read back from main state.

## Actual fallback versus references

[Next production43879945552](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43879945552) success:339pools,0alerts. Birdeye made2price attempts (6CU reserved),1successful,1HTTP429. It retained **2 token-reference fields** (price and aggregate liquidity). **Birdeye restored0circulating-cap gate fields and0complete pool snapshots.** Total estimated local31day CU99 at that point. Jupiter independently recovered23cap fields; these are not Birdeye recoveries and must not be combined as complete pool recoveries.

Token-wide liquidity and volume are never substituted for a single pool's liquidity, volume or transaction counts. A fallback cap needs exact mint, source age<=120s, positive explicitly circulating supply, price*supply agreement within2%, pool-price agreement within10%, and no scaled-UI ambiguity. FDV/total supply cannot substitute. Missing pool prices/volume/liquidity continue to reject candidates. Real-source API success does not mean all missing market data is repaired.

## Costs and limits

Official endpoint references checked16November2026:
- https://docs.birdeye.so/reference/get-defi-price :3CU/request.
- https://docs.birdeye.so/reference/get-defi-token_overview :18CU/request without optional money-flow includes.
- https://docs.birdeye.so/reference/get-defi-v3-token-market-data :10CU/request; inspected documentation only, not activated or called.
- https://docs.birdeye.so/docs/pricing :Standard30,000CU/month,1RPS. Older guides quote different endpoint costs; current endpoint reference is used.

Approved network endpoints are only price and overview. CU reserved before every attempt, including failures conservatively. Hard limits:24,000CU/rolling31days (80% of30,000),720/dayUTC,30/hourUTC,2calls/cycle. Daily cap is also conservative:31*720=22,320CU. Unknown/unmetered endpoint calls are rejected. No overage/top-up or subscription enabled.

Five-minute exact-mint cache, bounded20entries; source observation/update times are never renewed. Cache older than120s cannot supply a cap gate even if still available for request deduplication. Persisted usage survives restart/inactivity through the existing35day provider retention. Production runs serialize on existing solana-screening concurrency. Independent read-only integration jobs disable Birdeye network access and do not receive its key; they cannot spend outside the production ledger.

Local counters cover this scanner since tracking activation plus known imported legacy calls; they are conservative estimates, not Birdeye account billing or a measurement of other apps sharing the key. The limit cannot account for unseen prior usage or unrelated applications. Keep any such usage within the remaining account allowance.

## Rate limits and health

Initial unmetered baseline43878125862 had aBirdeye429. First metered price/overview probe succeeded. The next two-price cycle still got a429 on its second call despite start-based spacing. PR23tightens pacing to start>=1.05s after the prior response completes, persisting that completion timestamp even on failure. Arrival jitter is a possible explanation, not a proven cause.429Retry-After is honored with bounded60–900s endpoint backoff.401backoff1hour,403endpoint backoff1day; denied overview does not disable price. A successful API call is not a promise that future429s disappear.

PR22reports planned CU/cycle limits separately from outages and explicitly marks missing mandatory pool fields as degraded. At43879945552, health remained degraded:209incomplete pools, Gecko backoff and Birdeye429. No fields are zero-filled and health is not made green by hiding missing data.

## Preserved production behavior

Helius successful in both metered production runs. RugCheck, DexScreener, configured Solana RPC and public fallback remain integrated. Existing Telegram getMe/getChat/getUpdates and durable STATE_PERSIST_OK succeed. Original ON/OFF, five-minute scheduler and six-hour health reservations retained; health not_due. No test candidate messages or automatic trades.

Final integration, release and production evidence is appended below. Structured proof: [audit/birdeye-standard-20261116.json](audit/birdeye-standard-20261116.json).

## Final verified release — 22:56 WIT

PR21, PR22 and PR23 merged; final code merge `0c29124df3c47d4fa93451a7e2e978eddeb2fc85`.

[Final integration 43880258383](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43880258383): **268 Python + 30 scheduler/runtime + 28 legacy web = 326 passed, 0 failed**. Includes budget persistence, exact-mint cache, timestamp freshness, denied-endpoint fallback, no aggregate pool substitution, unmetered-path rejection and response-completion pacing regression.

[Final production 43880557025](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43880557025) completed success on final code. Repeated 268 Python regressions; Telegram identity/chat/controls checks and STATE_PERSIST_OK. Scanner ON, health notification not_due.

| Final observed metric | Value |
|---|---:|
| Pools examined | 368 |
| Birdeye successful fresh price reads | 1 |
| Birdeye cache hits | 1 |
| New CU reserved this cycle | 3 |
| Estimated scanner CU in rolling 31 days, including known legacy import | 102 |
| Birdeye token-reference fields retained this cycle | 2 |
| Birdeye circulating-cap gate fields restored | 0 |
| Complete pool snapshots restored by hydration | 0 |
| Pools still missing mandatory data | 218 |
| Telegram candidate alerts | 0 |

Latest Birdeye endpoint status price=ok; earlier overview=ok retained with its original timestamp. Helius and Jupiter also ok. Gecko discovery/hydration returned ok this cycle. No new429 in this final cycle, which made only one new Birdeye request; this is not proof that all future multi-request cycles are free from rate limits. Final health remains **degraded solely for incomplete mandatory pool fields**, not a hidden API failure. Missing-field counts overlap: m5 price change163, liquidity60, market cap57, price6. Different populations/times mean comparisons are not controlled performance or profit tests.

The two reference fields are **token price and token aggregate liquidity**, not two restored pool-gate fields. Do not sum reference counters across runs as unique recoveries. No pool aggregate safety exception, synthetic signal or automatic trade was added.
