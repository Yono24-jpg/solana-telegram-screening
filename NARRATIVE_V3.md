# MAIL AI Narrative Hunter v3.0

Upgrade in place of the existing alert-only Python scanner, Telegram bot and Cloudflare scheduler. The original `scan()` remains available for rollback; production still calls `scanner_v2.run()`, now version 3.0. No wallet signing, swap submission or auto trading is implemented.

## Narrative discovery

Five public Google News RSS queries cover games/GTA, movies, AI, public figures and social-media trends, with direct publisher RSS fallbacks. Articles must be dated within 48 hours and cannot be future dated. A trend requires at least two publisher domains and distinct headlines. Source articles and publication times accompany alerts. Names match on word boundaries; a matching name is explicitly not proof of affiliation, authenticity, future returns or actual social-platform virality. No direct TikTok/X firehose is claimed.

Static named aliases, repeated named phrases and optional Workers AI entity extraction feed both new-pool discovery and up to five DexScreener narrative searches per scan. Model entities must appear in at least two independently attributed titles before admission. Untrusted headlines cannot control security decisions. Scores are transparent evidence rules, not profit probabilities.

Workers AI uses `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, only if the existing Cloudflare CI token has AI permission. Successful model use is recorded, never assumed. Cache is three hours, maximum eight attempted calls/day, 400 output tokens/call. Rules continue when AI is unavailable. No GPT model is claimed. No paid subscriptions or billing settings are enabled; existing account quotas still apply. Missing quota/key/permission is reported.

## Mandatory market gates

Pool age 60–86400 seconds, priority <=3600 seconds; actual reported marketCap $20000–$500000 (FDV cannot substitute); liquidity >=$10000; hourly volume >=$5000; five-minute buy/sell >=1.5. Existing conservative momentum, minimum buys, five-minute volume, liquidity/cap and anti-chase gates also remain. The market and narrative are revalidated after final pool refresh.

## Mandatory security gates

All legacy authority, distribution and provider checks must be complete. The v3 detailed report must match the mint and candidate pool. Only classic SPL Token is admitted; unsupported Token-2022 fails closed. Mint/freeze must be absent. Creator must be identified. Candidate pool LP must be reported >=95% locked and >=$10000 locked value. This is a third-party LP report, not an independent proof of every locker or lock duration.

Explicit insider coverage is required: null/missing networks are unknown, never zero. Any reported insider network or suspicious bundle/wash/creator/mutable metadata flags reject. Top ten token-account concentration <=30% and observed largest owner <=15% use the existing program-owned vault exclusion proofs. Creator holdings are read on-chain and must be <=5%; last five creator transactions are checked for candidate-token outflow in the last hour. This bounded history cannot prove the absence of hidden developer wallets.

At least twelve distinct buyer transactions and three distinct sellers from the recent provider sample must be independently retrieved as finalized transactions. Candidate pool, signing wallet, mint balance direction, recent block time, successful execution, and actual sell proceeds are checked. Four sampled buyers in the same slot or sharing a co-signer reject as suspicious bundle patterns. Existing repeat-size, buyer concentration and roundtrip heuristics remain. These are bounded samples, not complete Sybil/Jito detection. Historical sells do not guarantee future sales or every wallet's ability to sell.

Missing mandatory evidence blocks **all** alerts, including EARLY WATCH. Telegram delivery also checks v3 evidence, preserving the durable send reservation and restart deduplication.

## Operations

`mail-solana-scheduler` remains `*/5 * * * *`, with its Durable Object slot lock and active-run guard. One bounded scan per workflow replaces the three-scan/sleep loop to reduce duplicated work. Existing GitHub five-minute backup schedule and ON/OFF controls remain. No synthetic notifications are sent during validation. Reports in `reports/*.json` and `state.json:last_scan` include version, news availability, actual AI use, security rejection codes and dispatch/run identifiers.

## Validation

Run `python3 -m unittest -vb`, `node --test scheduler/test/*.test.mjs` after `npm ci` in `scheduler`, and `node --test cloudflare/*.test.mjs`. Synthetic fixtures remain offline in tests; production never uses test data. Full security-report shape/coverage can vary by pool and provider. Unsupported/incomplete data remains blocked rather than being silently downgraded.

Primary provider API reference: https://api.rugcheck.xyz/swagger/doc.json
