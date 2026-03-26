import os

# ──────────────────────────────────────────
# HYPERLIQUID
# ──────────────────────────────────────────
HL_WALLET_ADDRESS = os.getenv("HL_WALLET_ADDRESS", "")
HL_PRIVATE_KEY    = os.getenv("HL_PRIVATE_KEY", "")
HL_TESTNET        = os.getenv("HL_TESTNET", "true").lower() == "true"

# ──────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "713501457")

# ──────────────────────────────────────────
# STRATEGY: Bollinger Band + Breakout Filter
# ──────────────────────────────────────────
TRADING_PAIR     = os.getenv("TRADING_PAIR", "BTC")   # BTC, ETH, SOL, dll
TIMEFRAME        = os.getenv("TIMEFRAME", "1h")        # 1m, 5m, 15m, 1h, 4h
BB_PERIOD        = int(os.getenv("BB_PERIOD", "20"))
BB_STD           = float(os.getenv("BB_STD", "2.0"))
ADX_THRESHOLD    = float(os.getenv("ADX_THRESHOLD", "25"))   # > nilai ini = trending, skip
VOLUME_SPIKE_X   = float(os.getenv("VOLUME_SPIKE_X", "2.0")) # volume > 2x normal = skip

# ──────────────────────────────────────────
# RISK MANAGEMENT
# ──────────────────────────────────────────
TRADE_SIZE_USDC  = float(os.getenv("TRADE_SIZE_USDC", "50"))   # per trade
LEVERAGE         = int(os.getenv("LEVERAGE", "5"))
TAKE_PROFIT_PCT  = float(os.getenv("TAKE_PROFIT_PCT", "2.0"))  # %
STOP_LOSS_PCT    = float(os.getenv("STOP_LOSS_PCT", "1.0"))    # %
MAX_DAILY_LOSS   = float(os.getenv("MAX_DAILY_LOSS", "50"))    # USDC, bot berhenti kalau melebihi

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
