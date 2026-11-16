# Helius live verification — 16 November 2026

Existing MAIL AI Narrative Hunter v5, bot and mail-solana-scheduler retained. ALERT ONLY.

## Production proof

[Production run43847478235](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43847478235) completed success on merge `48051b2ff303c8cbef4630559740fc446f3c3370`, 19:17 WIT. 259 Python tests repeated successfully; getMe/getChat/getUpdates and STATE_PERSIST_OK. Finalized slot **470095014** came from Helius; report has `helius_used:true`, `valid_finalized_slot:true`, provider `helius:ok`, and successful method `getSlot:1`. Production cycle used one estimated credit, scanned275 pools, sent0 alerts. The one-credit ledger was read back from persisted main state. ON stays true; six-hour health not_due, existing delivery408 retained.

This production cycle had no security-stage candidate. It proves a successful Helius RPC in production, not that all developer/insider/whale checks ran on a passing production candidate.

## Live wallet audit

[Read-only integration43847296226](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43847296226) succeeded: 259 Python +30 scheduler/runtime +28 legacy web = **317 tests passed,0 failed**. The workflow receives HELIUS_API_KEY through Actions secrets and no Telegram/signing key. Audit data is live, not fixtures.

Initial dedicated wallet audit:33 Helius attempts,32 successful RPC results; methods: getSlot1, getTokenAccountsByOwner2, getSignaturesForAddress8, getTokenSupply2, getTokenLargestAccounts2, getAccountInfo4, getTransaction13. Two repeated finalized transaction reads were served from cache. One missing/invalid result correctly attempted fallback. All successful method counts are attributed to Helius, not fallback.

| Token | Developer | Large-account evidence | Insider and funding limits |
|---|---|---|---|
| cbBTC | Reported creator holdings0%; no qualifying recent developer transactions in the five-signature sample | Largest token accounts20.3167% and18.6544% of supply | RugCheck reported0 network members; direct funding sample incomplete; not cleared |
| ZCAT | Reported creator holdings0.0001134%; five recent transactions inspected with no outflow rejection in that sample | Largest token accounts3.0296% and2.1548% | RugCheck reported906 members in one network; funding sample incomplete; not cleared |

Large accounts can be pool vaults, custodians or wallets. They are not automatically attributed whales. Wallet transactions include finalized signature, slot, timestamp, signer check, success flag and token delta; old movements are not current purchases, and token movement alone is not a supported pool swap. Provider-reported developer identity is not independently proven authorship. A zero provider count is not proof that hidden insiders do not exist.

Follow-up expands holder-owner sampling to allow four buyer wallets when actually observed, adds movement age/supply percentage, and retains fail-closed incomplete funding results. It does not reduce any production security threshold. Full funded-wallet and whale buy/sell clearance remains dependent on adequate current finalized swaps and existing mandatory security gates.

## Free-tier controls

Official documentation checked16 November2026:
- https://www.helius.dev/docs/billing/credits : allowed standard methods, including getTransaction/getSignaturesForAddress, currently1credit/request.
- https://www.helius.dev/docs/billing/plans : Free1M credits/month,10RPC requests/sec.

Local production caps: **80 requests/cycle,20,000/day UTC,600,000 over rolling31days,2 request starts/sec**. All attempts reserve one estimated credit, including failures conservatively. Ledger retained35days, survives process restart/inactivity, and expires old rolling days. Finalized transaction reads deduplicate within a cycle; mutable account snapshots and missing results are not cached. Quota exhaustion,401/403,429 and transient RPC errors retain fallback/fail-closed behavior.

The600k rolling31day ceiling leaves400k of a1M allowance for audits/other use. It is this scanner's local estimate from tracking activation, not the account invoice, total account consumption or billing-cycle reset date. Independent read-only audit jobs and other apps are outside the persisted production ledger; their usage consumes the same Helius account allowance. No paid API, automatic top-up or subscription was enabled.

## Remaining health

Helius is connected. Overall scanner remains degraded for Gecko unavailable/provider_backoff, unrelated to Helius authentication. Birdeye/X access remains as previously configured. Cron five minutes, ON/OFF, original Telegram bot and six-hour health logic unchanged. No key printed, synthetic alerts sent or auto trading enabled.

Structured proof: [audit/helius-verification-20261116.json](audit/helius-verification-20261116.json).

## Follow-up audit verification

[Integration43847670318](https://github.com/Yono24-jpg/solana-telegram-screening/actions/runs/43847670318) completed success after audit sampling fix. Dynamic selection changed to cbBTC/JUP.42 Helius attempts; Helius successfully returned15 finalized transactions and8 account reads; one getTokenLargestAccounts result came from configured RPC fallback and is attributed separately. cbBTC developer sample0holdings,0recent; JUP developer proof incomplete. Both funding checks remain incomplete and do not clear security. Previous production ledger1 plus42 audit attempts explains the audit-local estimated43; audit did not write these42 to production. No claim of42 additional persisted production credits. PR20 updates only the read-only audit; production security release and proof above remain unchanged.
