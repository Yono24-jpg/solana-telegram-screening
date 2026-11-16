# MAIL AI Narrative Hunter v3.0

Upgrade in place of the existing alert-only Python scanner, Telegram bot and Cloudflare scheduler. The original `scan()` remains available for rollback; production still calls `scanner_v2.run()`, now version 3.0. No wallet signing, swap submission or auto trading is implemented.

## Narrative discovery

Five public Google News RSS queries cover games/GTA, movies, AI, public figures and social-media trends, with direct publisher RSS fallbacks. Articles must be dated within 48 hours and cannot be future dated. A trend requires at least two publisher domains and distinct headlines. Source articles and publication times accompany alerts. Names match on word boundaries; a matching name is explicitly not proof of affiliation, authenticity, future returns or actual social-platform virality. No direct TikTok/X firehose is claimed.

Static named aliases, repeated named phrases and optional Workers AI entity extraction feed both new-pool discovery and up to twelve bounded DexScreener narrative/alias searches per scan. Model entities must appear in at least two independently attributed titles before admission. Untrusted headlines cannot control security decisions. Scores are transparent evidence rules, not profit probabilities.

Workers AI runs through an AI binding on the existing `mail-solana-scheduler`, authenticated with a short-lived GitHub Actions OIDC token. The Worker verifies issuer, audience, RSA signature against GitHub JWKS, immutable repository/owner IDs, main branch, exact `screen.yml` workflow, event type and token times. Other workflows and public callers cannot invoke inference. No extra shared secret or long-lived AI key is required. Existing scheduler dispatch/deduplication storage remains separate from the AI budget/cache.

Requested model: `@cf/meta/llama-3.3-70b-instruct-fp8-fast`. Actual returned model is recorded if the provider reports a different backend. Cache is three hours, maximum eight attempted calls/day (claimed durably before inference), 400 output tokens/call. Rules continue when AI is unavailable, with explicit status and no false model claim. No GPT model is claimed. No paid subscriptions or billing settings are enabled; existing account quotas still apply. The earlier direct CI token was rejected during production verification and is no longer passed to the scanner.

## Mandatory market gates

Pool age 60–86400 seconds, priority <=3600 seconds; actual reported marketCap $20000–$500000 (FDV cannot substitute); liquidity >=$10000; hourly volume >=$5000; five-minute buy/sell >=1.5. Existing conservative momentum, minimum buys, five-minute volume, liquidity/cap and anti-chase gates also remain. The market and narrative are revalidated after final pool refresh.

## Mandatory security gates

All legacy authority, distribution and provider checks must be complete. The v3 detailed report must match the mint and candidate pool. Only classic SPL Token is admitted; unsupported Token-2022 fails closed. Mint/freeze must be absent. Creator must be identified. Candidate pool LP must be reported >=95% locked and >=$10000 locked value. This is a third-party LP report, not an independent proof of every locker or lock duration.

Explicit insider coverage is required: null/missing networks are unknown, never zero. Any reported insider network or suspicious bundle/wash/creator/mutable metadata flags reject. Top ten token-account concentration <=30% and observed largest owner <=15% use the existing program-owned vault exclusion proofs. Creator holdings are read on-chain and must be <=5%; last five creator transactions are checked for candidate-token outflow in the last hour. This bounded history cannot prove the absence of hidden developer wallets.

At least twelve distinct buyer transactions and three distinct sellers from the recent provider sample must be independently retrieved as finalized transactions. A supported AMM swap instruction referencing the pool, signing wallet, mint balance direction, recent block time, successful execution, and actual sell proceeds are checked. Four sampled buyers in the same slot or sharing a co-signer reject as suspicious bundle patterns. Existing repeat-size, buyer concentration and roundtrip heuristics remain. These are bounded samples, not complete Sybil/Jito detection. Historical sells do not guarantee future sales or every wallet's ability to sell.

Missing mandatory evidence blocks **all** alerts, including EARLY WATCH. Telegram delivery also checks v3 evidence, preserving the durable send reservation and restart deduplication.

## Operations

`mail-solana-scheduler` remains `*/5 * * * *`, with its Durable Object slot lock and active-run guard. One bounded scan per workflow replaces the three-scan/sleep loop to reduce duplicated work. Existing GitHub five-minute backup schedule and ON/OFF controls remain. No synthetic notifications are sent during validation. Reports in `reports/*.json` and `state.json:last_scan` include version, news availability, actual AI use, security rejection codes and dispatch/run identifiers.

## Validation

Run `python3 -m unittest -vb`, `node --test scheduler/test/*.test.mjs` after `npm ci` in `scheduler`, and `node --test cloudflare/*.test.mjs`. Synthetic fixtures remain offline in tests; production never uses test data. Full security-report shape/coverage can vary by pool and provider. Unsupported/incomplete data remains blocked rather than being silently downgraded.

Primary provider API reference: https://api.rugcheck.xyz/swagger/doc.json


## Real-token discovery repair — 16 November 2026

The read-only four-token audit found incomplete snapshots and missed discovery coverage. Discovery now combines three new-pool pages, two trending-pool pages, canonical narrative names and bounded related aliases (including FiveM under the independently sourced GTA topic). A complete snapshot is preferred over incomplete search results. Present pools with missing mandatory v3 fields are retried in bounded pair batches. Hourly volume and actual market cap are included in completeness checks; FDV never replaces market cap. Two incomplete snapshots are never stitched into a synthetic complete one.

`discovery_watchlist.json` explicitly records the four user-requested, resolved CAs and their source pool URLs. The production workflow enables this **retrieval watchlist**, not a security allowlist. Entries expire at pool age 24 hours, with a maximum lifetime of 24 hours and maximum 20 entries. Audit reports label this targeted lookup separately from general discovery. Names are not unique: the trending Rockstar mint is `9HFUEab7sompLDPTAaTGkryMNGbtBaFMhHMVpJEBpump`; the unrelated same-name mint `4cRMcRAV1at19fUgj2aYBKoM9nVzA8s48mLK9W7a7DEu` is retained only as an ambiguity example in the first audit artifact.

Security thresholds and the strict Token-2022 exclusion remain unchanged. Known unsupported token programs are rejected early using the on-chain owner, avoiding unnecessary public-feed calls. Missing trade samples, null insider coverage or unavailable market fields remain unknown and block alerts. Cyber Dacity's name alone does not prove a GTA relationship; it is not assigned a passing narrative score merely to satisfy this test.

The dedicated `Read-only Real Token Audit` workflow receives only the RPC secret. It has no Telegram credentials, signing key, transaction submission, state-write permission or signal delivery. It checks each security component independently even when market/Token-2022 gates already reject, and uploads timestamped evidence. A shared conservative Gecko request budget prevents the diagnostic from resetting the free-feed limit per token.
