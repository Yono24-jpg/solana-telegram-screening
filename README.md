# Solana Telegram Screening

Alert-only. No wallet credentials, transaction signing or trading.

GitHub Actions standard Linux runner, public repository, scheduled every five minutes. Schedules can be delayed or dropped; this is not a continuous real-time service. ON/OFF is processed on each run and requires a group administrator. Telegram webhook must not be configured on this dedicated bot.

Pool age is rechecked immediately before sending, maximum 600 seconds. Up to five candidates per scan, ranked using liquidity (40%), five-minute volume (35%), and buy/sell ratio (25%) on logarithmic scales. Minimum liquidity $10,000, five-minute volume $1,500, 12 buys, buy/sell ratio 1.2. Missing metrics or failed checks discard candidates. Standard SPL mint required, no mint/freeze authorities; Token-2022 rejected. Holder concentration is not checked and is clearly disclosed in alerts. These checks do not guarantee safety or profit.

Discovery uses DexScreener latest profiles and boosts. It does not enumerate all newly created Solana pools; tokens missing from these feeds cannot be found. No alert when no candidate passes. Repeated alerts are suppressed for 24 hours. Ranking covers only the successfully checked candidates.

Required GitHub Actions secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Optional SOLANA_RPC_URL. Without a configured RPC, public Solana RPC is used; rate limits cause silent candidate rejection, never bypasses.

The bot must be in the destination group and able to send messages. The first successful run sends a clearly labeled connection test with ON/OFF buttons and starts OFF. No scan data is fabricated for testing. Runtime state records callback offset, enabled flag and already sent public mint addresses only. Secrets never enter repository files or logs.

GitHub may disable schedules for inactive public repositories after 60 days. GitHub Actions availability and API limits apply.
