# v5.4 — Solana transaction v1 read compatibility

17 November 2026. Follow-up to merged PR #30; the existing scanner and bot are retained.

## Observed defect

Production discovery lists recent signatures but repeatedly fails when fetching their transaction bodies. Every transaction reader still advertises `maxSupportedTransactionVersion: 0`. A paired read of the exact production-pending signature `2Bt8VNpb3PZajzWuTbjcaii5pJUKEgzMeHSxAnEygJ5aCswVCqrF9o8GM8MdaXA2M7ULvHuLJv94kX3xpUpZU7s1` against the official public Solana endpoint returned JSON-RPC `-32015` with maximum 0 and a finalized version-1 transaction with maximum 1. Commitment and `jsonParsed` encoding were identical.

The [Solana transaction-version documentation](https://solana.com/docs/core/transactions/versioned-transactions) confirms v1 is active and maximum 0 rejects its bodies while signature enumeration still works. The [network upgrade notes](https://solana.com/upgrades/larger-transaction-sizes) prescribe the integer 1 for read clients. This is a concrete retrieval failure, not evidence that every zero alert was caused by transaction versions.

## Change

Advertise maximum version 1 in discovery, sampled reserve changes, mint-creation proof, developer history, sell/buyer evidence, direct-funding checks and the Helius audit. Continue to consume resolved `jsonParsed` instructions, signer flags and pre/post balances; no raw binary decoder, compute-budget inference, transaction submission or signing is added. Legacy and v0 responses remain supported.

Record numeric JSON-RPC error codes and explicitly classify `-32015` without retaining provider messages, URLs or keys. Unsupported future versions and missing evidence remain unavailable. Existing free API budgets, market thresholds and every safety rule remain unchanged. X is OFF; the five-minute scheduler, ON/OFF and ALERT ONLY are retained.

## Validation

326 Python tests pass (318 existing plus eight v1 regressions). New cases require the v1 opt-in through the actual discovery, reserve-sample, mint, developer, funding and transaction-evidence call paths. They preserve rejection of failed transactions, incorrect mint balances, developer outflows, missing sell proceeds and shared funders. Finalized-cache behavior for legacy/v0/v1 and secret-safe error reporting are covered. `git diff --check` passes.

A larger fixed-signature live comparison is being collected separately. At least 12 successful post-repair production cycles are required before production verification is complete; pre-repair v5.4 cycles do not satisfy that requirement.
