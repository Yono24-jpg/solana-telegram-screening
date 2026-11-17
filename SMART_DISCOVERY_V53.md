# MAIL AI Narrative Hunter v5.3 — SMART DISCOVERY

Upgrade of the existing v5.2 scanner. Bot, Telegram controls, cron, X OFF and ALERT ONLY are retained. Market/security gates are unchanged; internal narrative leads never authorize a message.

## Why the reported coverage fell

41.23% (94/228), the immediate pre-upgrade 48.59%, and the later 31.64% (1254/3963 observations) used changing pool samples. They cannot establish an algorithm regression. The later verification showed missing five-minute price change, liquidity and volume; Dex responses were successful but partial, and Gecko hydration had 12 HTTP 429s, 35 backoff skips, and only five successful batches. Broader young/partial-pool retention can also expand the denominator. No denominator is removed to raise the percentage.

The v5.2 artifact from run 44070114701, artifact 14321738237, contains 30 archived pool observations: 11 complete, 19 incomplete, nine aged 1–60 minutes. Their exact mint/pair identities and initial missing fields are preserved in audit/cohort-v52-to-v53.json. They are a nonrandom diagnostic sample, not a safety allowlist. v5.3 re-requests these same identities for six hours after the baseline, reports absent pools as incomplete, and never reuses the archived market numbers. Market time changes remain a confounder; this is not causal A/B evidence. Reports also compare identical pools immediately before and after the current recovery stage.

## Implementation

- Read-only finalized getSignaturesForAddress on Raydium CPMM's creation fee receiver, then at most six getTransaction reads per cycle within an 18-second sub-budget. Match the exact CPMM program, initialize discriminator, fee receiver, account positions, transaction signature and successful metadata. Recent creation leads carry no USD liquidity, volume, price, cap or safety claim. RPC discovery is a bounded CPMM sample, not complete coverage of all Solana DEXes; existing public discovery and dynamic global narrative categories continue.
- Durable transaction-result cache avoids decoding the same finalized transaction every cycle. Failed/missing transactions retry after five minutes. At most 200 signature records, two-hour retention.
- Durable queue retains at most 300 identities for one day and services at most 80 due incomplete pools per recovery stage. Young pools are prioritized, older checks rotate. Only requests that actually start update retry timestamps. Identity cache contains no stale market values. Every Telegram alert still requires the existing fresh final quote and all security gates.
- Gecko discovery uses one newest-pool page instead of five discovery pages. All Gecko calls share a three-request cycle ceiling, 12-second spacing, and persisted exponential HTTP 429 backoff (five minutes up to 30 minutes), respecting Retry-After within the same conservative ceiling.
- Helius RPC uses the existing daily/rolling credit ledger, max 80 attempts/cycle and 2 starts/second. New reads are standard RPC, not enhanced parsing, DAS, paid streams or purchased plans. Existing Birdeye limits stay in place.
- same-pool-v53.json includes each sample identity, missing-field transition, fixed denominator and source mix. Summary logs preserve comparisons without claiming 90% completeness or token safety.

## Primary references

- https://solana.com/docs/rpc/http/getsignaturesforaddress
- https://solana.com/docs/rpc/http/gettransaction
- https://github.com/raydium-io/raydium-cp-swap/blob/master/programs/cp-swap/src/instructions/initialize.rs
- https://github.com/raydium-io/raydium-docs-v1/blob/main/reference/program-addresses.mdx
- https://www.helius.dev/docs/billing/credits (standard RPC, getSignaturesForAddress and getTransaction: one credit/request; application reservations include failures and are not account billing)

Production verification is recorded separately after deployment. Local tests alone are not production evidence.
