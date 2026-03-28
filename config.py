import os

# ──────────────────────────────────────────
# ACTIVE EXCHANGE  (bybit | hyperliquid)
# ──────────────────────────────────────────
ACTIVE_EXCHANGE  = os.getenv("ACTIVE_EXCHANGE", "bybit")  # bybit | hyperliquid | polymarket

# ──────────────────────────────────────────
# BYBIT
# ──────────────────────────────────────────
BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_MAINNET    = True   # selalu mainnet
# Proxy HTTP/SOCKS5 (opsional): "http://user:pass@host:port"
BYBIT_PROXY      = os.getenv("BYBIT_PROXY", "")
# Base URL override — gunakan Cloudflare Worker untuk bypass CloudFront block
# Default: https://api.bybit.com
# Contoh CF Worker: https://bybit-proxy.username.workers.dev
BYBIT_BASE_URL   = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com")

# ──────────────────────────────────────────
# HYPERLIQUID
# ──────────────────────────────────────────
HL_WALLET_ADDRESS = os.getenv("HL_WALLET_ADDRESS", "")
HL_PRIVATE_KEY    = os.getenv("HL_PRIVATE_KEY", "")
HL_TESTNET        = os.getenv("HL_TESTNET", "true").lower() == "true"

# ──────────────────────────────────────────
# POLYMARKET
# ──────────────────────────────────────────
POLY_WALLET_ADDRESS  = os.getenv("POLY_WALLET_ADDRESS", "")
POLY_PRIVATE_KEY     = os.getenv("POLY_PRIVATE_KEY", "")   # untuk trading (L1 auth)
POLY_BOT_SIZE        = float(os.getenv("POLY_BOT_SIZE", "10"))
POLY_BOT_MAX_MARKETS = int(os.getenv("POLY_BOT_MAX_MARKETS", "5"))

# ──────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "713501457")

# ──────────────────────────────────────────
# PERSONA (Trading Character)
# ──────────────────────────────────────────
# Pilihan: warren_buffett, paul_tudor_jones, ray_dalio, george_soros,
#          michael_burry, bill_ackman, li_ka_shing, naruto, tom_lee, custom
ACTIVE_PERSONA   = os.getenv("ACTIVE_PERSONA", "warren_buffett")

# ──────────────────────────────────────────
# STRATEGY (shared defaults)
# ──────────────────────────────────────────
TRADING_PAIR     = os.getenv("TRADING_PAIR", "BTC")
TIMEFRAME        = os.getenv("TIMEFRAME", "1h")
# Nilai BB & ADX diambil dari persona, tapi bisa di-override via env
BB_PERIOD        = int(os.getenv("BB_PERIOD", "0")) or None
BB_STD           = float(os.getenv("BB_STD", "0")) or None
ADX_THRESHOLD    = float(os.getenv("ADX_THRESHOLD", "0")) or None
VOLUME_SPIKE_X   = float(os.getenv("VOLUME_SPIKE_X", "0")) or None

# ──────────────────────────────────────────
# RISK MANAGEMENT (shared defaults)
# ──────────────────────────────────────────
TRADE_SIZE_USDC  = float(os.getenv("TRADE_SIZE_USDC", "50"))
LEVERAGE         = int(os.getenv("LEVERAGE", "0")) or None   # None = pakai dari persona
TAKE_PROFIT_PCT  = float(os.getenv("TAKE_PROFIT_PCT", "0")) or None
STOP_LOSS_PCT    = float(os.getenv("STOP_LOSS_PCT", "0")) or None
MAX_DAILY_LOSS   = float(os.getenv("MAX_DAILY_LOSS", "50"))

# ──────────────────────────────────────────
# PER-EXCHANGE BOT SETTINGS  (runtime, dapat diubah via dashboard)
# ──────────────────────────────────────────
# Bybit Bot
BYBIT_BOT_PAIR      = os.getenv("BYBIT_BOT_PAIR", "BTC")
BYBIT_BOT_TIMEFRAME = os.getenv("BYBIT_BOT_TIMEFRAME", "5m")
BYBIT_BOT_LEVERAGE  = int(os.getenv("BYBIT_BOT_LEVERAGE", "10"))
BYBIT_BOT_SIZE      = float(os.getenv("BYBIT_BOT_SIZE", "50"))
BYBIT_BOT_TP        = float(os.getenv("BYBIT_BOT_TP", "0")) or None
BYBIT_BOT_SL        = float(os.getenv("BYBIT_BOT_SL", "0")) or None
BYBIT_BOT_PERSONA   = os.getenv("BYBIT_BOT_PERSONA", "quantitative_trader")

# Hyperliquid Bot
HL_BOT_PAIR         = os.getenv("HL_BOT_PAIR", "BTC")
HL_BOT_TIMEFRAME    = os.getenv("HL_BOT_TIMEFRAME", "1h")
HL_BOT_LEVERAGE     = int(os.getenv("HL_BOT_LEVERAGE", "5"))
HL_BOT_SIZE         = float(os.getenv("HL_BOT_SIZE", "50"))
HL_BOT_TP           = float(os.getenv("HL_BOT_TP", "0")) or None
HL_BOT_SL           = float(os.getenv("HL_BOT_SL", "0")) or None
HL_BOT_PERSONA      = os.getenv("HL_BOT_PERSONA", "warren_buffett")

# ──────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────
DASHBOARD_HOST     = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT     = int(os.getenv("PORT", "8000"))
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "sumbubotol123")

# ──────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trading.db")

# ──────────────────────────────────────────
# BOT CONTROL
# ──────────────────────────────────────────
BOT_ENABLED      = os.getenv("BOT_ENABLED", "true").lower() == "true"
POLL_INTERVAL    = int(os.getenv("POLL_INTERVAL", "60"))  # detik antar cek signal
