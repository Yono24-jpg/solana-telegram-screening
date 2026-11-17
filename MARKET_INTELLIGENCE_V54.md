# MAIL AI Narrative Hunter v5.4 — REAL-TIME MARKET INTELLIGENCE

Existing v5.3 project. This remains five-minute HTTP polling, not a sub-minute stream. No market/security gates, Telegram authorization, X policy or paid API settings are relaxed.

## Problem and measured local baseline

v5.3 production rejects candidates before final security. Its first-return reasons obscure overlapping failures. The 30 archived snapshots from run 44086217079 (artifact 14328614662) are frozen in audit/frozen-v53-v54.json. Replaying identical snapshots produces the same eligibility decisions: 20 cap rejections, 4 missing market data, 2 weak activity, 2 hourly volume, 1 liquidity, 1 late/falling price. v5.4 adds 660 explicit gate checks, exposing 145 failed and 87 unknown checks, including unavailable historical narrative rather than inventing it. These are overlapping diagnostics, not 660 independent tokens or additional filters. See audit/backtest-v54-frozen.json.

The existing memory contains extreme reported price jumps. They are unverified observations, not proved missed safe trades or profits. The new review separates provider-reported >=50% hourly risers (with >=10k observed USD liquidity) from historical extreme anomalies and records current blockers and whether the same mint/pair was previously recorded. Historical safety absent at first observation remains unknown. Initial decision is now preserved separately from later decisions.

## Bounded additions

- Full market-filter audit with values, rules, failed/unknown/not-applicable status and original primary rejection. Score/mode and narrative remain distinct. Security stages not reached are explicitly identified. Auditing never sends or changes the real eligibility decision.
- Official creation layouts for Pump.fun create/create_v2, PumpSwap create_pool, Raydium CPMM initialize and Meteora DAMM v2 initialization variants. Registry contains minimal account roles, discriminators, fixed addresses, source URLs and full upstream-IDL SHA256 hashes. Failed, unmatched-signature, future/old, spoofed-program and fixed-account mismatches are rejected.
- Pump.fun scans its official mint-authority PDA, which targets creation transactions rather than the whole swap stream. CPMM retains its fee-receiver index. A bounded PumpSwap/Meteora program sample alternates. At most three signature reads and six transaction reads per cycle, within a 24-second sub-budget; durable cache/rotation are retained. This is sampled protocol coverage, not full-chain coverage. The previous CPMM-only parser runs on exactly the same captured transactions for comparison; new polling policy is not a causal A/B test.
- A bonding curve remains a bonding-curve lead, not a fabricated indexed AMM pool. Its mint is resolved through the public DEX token endpoint; unindexed curve leads remain internal in a bounded one-hour queue (100 identities, at most 30 mint resolutions per cycle) and are rechecked after their creation signature is cached. Pool age comes from the actual indexed pool, not the earlier mint/curve creation.
- GeckoTerminal hydration is paced at 12-second intervals (maximum five calls/minute), limited to five calls per scan and nine attempts per rolling minute, with persisted exponential HTTP 429 backoff. The new-pool query uses one call; the remaining four calls can hydrate up to 80 prioritized pool identities in four batches. Calls that hit a free budget or provider backoff remain visible, so this does not promise complete market data. The public API documents an approximate 10 calls/minute limit: https://api.geckoterminal.com/docs/index.html
- One young PumpSwap pool can be sampled with at most two finalized transactions within 12 seconds. Exact mint/pair, swap program/layout, vault account indices and pre/post token balances are bound. Multi-touch ambiguous transactions are refused. BUY/SELL and reserve changes are sampled token-unit observations; fees are included in net changes. No full five-minute volume, USD liquidity or USD market cap is claimed or copied into market gates. Concentrated-liquidity reserve ratios are not used as spot prices.
- INTERNAL MARKET WATCH retains young active pools even without a proven narrative, with explicit blockers and security_verified=false. Only the existing VERIFIED ALERT pipeline can send a token alert after all existing gates and fresh final quote.
- The same 30-pool v5.3 sample is reobserved by exact mint/pair in production. Absent pools stay in the denominator. Per-run artifacts preserve gate details, RPC transaction evidence, lower-bound chain samples, internal research and gainer review.

## Validation and limits

318 local Python tests pass; original 299 regressions remain. New tests cover every pinned initialization layout, long Borsh payloads, spoofing/failure/time limits, nested instructions, cache persistence, curve/pool separation, actual vault-unit changes, ambiguous swaps, eligibility parity and internal-only status. GitHub CI and at least 12 production cycles must be verified separately before completion is claimed.

Benefit targets are observable discovery outside CPMM, complete filter explanations on identical snapshots, and lower-bound chain observations where supported. No promise of more safe alerts, 90% data completion, profitable backtests or reliable historical safety is made. Empty/missing values stay unknown. Free API ledgers remain authoritative for application limits; they are not account billing.

Primary layout sources:

- https://github.com/pump-fun/pump-public-docs/blob/main/idl/pump.json
- https://github.com/pump-fun/pump-public-docs/blob/main/idl/pump_amm.json
- https://github.com/MeteoraAg/damm-v2-sdk/blob/main/src/idl/cp_amm.json
- https://github.com/raydium-io/raydium-cp-swap/blob/master/programs/cp-swap/src/instructions/initialize.rs
- https://solana.com/docs/rpc/http/gettransaction
- https://solana.com/docs/rpc/http/getsignaturesforaddress
