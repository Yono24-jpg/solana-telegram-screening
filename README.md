# Solana Telegram Screening

Alert-only screening for early Solana pool candidates, with Indonesian Telegram alerts and ON/OFF controls. No wallet credentials, signing or trading.

## Eligibility and early momentum

Pool age: 5 minutes–5 hours. This is pool age, not verified mint creation time. An old token may create a new pool. The feed does not independently classify all tokens as meme coins.

Minimum liquidity $10,000, five-minute volume $1,500, 12 buys and BUY/SELL ratio 1.5. Verified market cap is required; liquidity must be at least 8% of market cap.

A candidate requires two public market observations of the same pool and mint, 5–15 minutes apart, so five-minute volume windows do not overlap. A cold start waits silently for a baseline. Missing or stale observations never create a signal. Further requirements:

- Five-minute volume grows at least 10% against the baseline.
- BUY count does not fall; at least three SELL transactions are visible. SELL activity is not proof that every wallet can sell.
- Liquidity retains at least 90% of the baseline.
- Price changes 0–15% over five minutes and -15% to +60% over one hour.
- Price moves between -5% and +15% against the baseline. Baseline is a previous observed price, not launch price.

## Transparent score

This is a rule-based score, not an AI prediction, win rate, profit probability or backtested strategy. Minimum score 70/100.

| Component | Maximum | Rule |
| --- | ---: | --- |
| BUY pressure | 25 | BUY share from 50% to 75% of transaction count |
| Volume growth | 25 | Current five-minute volume / baseline volume, capped at 2x |
| Liquidity depth | 20 | Liquidity / market cap, capped at 15% |
| BUY activity | 15 | Current five-minute BUY count, capped at 30 |
| Early price | 15 | Higher points for smaller nonnegative five-minute price changes |

Passing candidates are ranked by this score. Up to 30 unseen mints receive security checks; up to five fully passing alerts are sent. Market metrics and quality are rechecked after refresh and immediately before delivery. Rejected candidates remain silent.

Alerts include score, explicit reasons, observed volume growth, BUY share, liquidity retention, price changes, copyable mint, DexScreener and Axiom links. No fabricated signal is sent for testing.

## Security

Mint and freeze authorities must be revoked. SPL Token and Token-2022 with supported metadata-only extensions are accepted; other extensions fail closed. Top ten token accounts must not exceed 30% of supply. This conservative account check includes pool vaults and is not a distinct-wallet analysis; it may reject otherwise legitimate pools.

RugCheck danger/critical flags or normalized score >=60 reject the candidate. Missing RPC or provider evidence rejects the candidate. No check guarantees absence of rugpull, manipulation, wash trading, losses or successful future selling.

## Discovery and operation

Discovery retains DexScreener profiles, boosts, community takeovers and ads plus three pages of GeckoTerminal new Solana pools normalized with DexScreener. Feed coverage is incomplete; paid promotion is not an endorsement.

GitHub Actions uses a five-minute cron, with four scan cycles separated by 45-second pauses. Each bot invocation has a 30-second network budget to leave time for persistence in the five-minute job. Schedules can be delayed or dropped, so this is not a continuous real-time launch monitor.

ON/OFF callbacks are processed during runs and require destination administrator rights. Only ON/OFF buttons are shown. Existing control state is retained. Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID; optional SOLANA_RPC_URL. The dedicated bot must be allowed to post in its group, supergroup or channel with no webhook configured.

State stores controls, public mint delivery history and bounded public price/volume observations. Observations survive runs and restarts through the workflow state merge: up to 200 pools, 12 snapshots each, maximum retention 30 minutes. Delivery suppression lasts five hours.

Run `python3 -m unittest -v` to test without sending real Telegram messages. GitHub may disable schedules after repository inactivity.

API references: https://docs.dexscreener.com/api/reference and https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

