# Solana Telegram Screening

Alert-only scanner for new Solana pools. No wallet credentials, signing or trading.

## Filters

Pool age must be 5 minutes–5 hours, including a final check after risk requests. This is pool age, not verified mint creation time: an old token can create a new pool. The scanner does not independently classify every token as a meme coin.

Minimum liquidity $10,000, five-minute volume $1,500, 12 buys in five minutes, BUY/SELL ratio 1.5. Liquidity must also be at least 8% of verified market cap. Missing metrics fail closed. Sharp price drops and already pumped tokens are rejected using the existing momentum thresholds.

Mint and freeze authorities must be revoked. SPL Token and Token-2022 with only the supported metadata extensions are accepted; other Token-2022 extensions fail closed. Top ten token accounts must not exceed 30% of supply; this is not a distinct-wallet analysis and can include pool vaults. RugCheck danger/critical flags or normalized risk score of 60 or more reject a token. Missing RPC or risk data rejects a token. These checks do not guarantee safety or profit.

## Discovery and alerts

Uses DexScreener profiles, boosts, community takeovers and ads, plus three pages of GeckoTerminal new Solana pools normalized through DexScreener. Feed coverage is incomplete. Tokens outside these feeds cannot be found.

Up to 30 unseen market-qualified mints receive security checks per scan. Sent tokens are excluded before ranking. Up to five passing candidates are sent, with Indonesian metrics, copyable mint, DexScreener and Axiom links. Ranking uses logarithmic liquidity, volume and BUY/SELL ratio with weights 40/35/25. Rejected or unverified candidates are not sent. Delivery suppression lasts five hours.

## Operation

GitHub Actions runs on a five-minute cron, with four scan cycles separated by 60 seconds in each run. Runs have a five-minute timeout and can be delayed or dropped; this is not continuous real-time monitoring. ON/OFF callbacks are processed during a run and require destination administrator rights. Only ON/OFF buttons are shown.

Required secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Optional SOLANA_RPC_URL; public Solana RPC is used otherwise and rate limits reject unverified candidates. The dedicated bot must be allowed to send messages to its group, supergroup or channel, with no webhook configured. First successful initialization sends a connection test and starts OFF. Existing saved control state is retained on updates.

State stores the enabled flag, callback offset and sent public mints, without secrets. GitHub may disable schedules after repository inactivity. Run `python3 -m unittest -v` to check filters without sending Telegram messages.
