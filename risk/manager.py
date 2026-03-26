from datetime import datetime, timezone
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


class RiskManager:
    """
    Kelola risiko per trade dan harian.
    - Cek apakah boleh buka trade baru
    - Hitung ukuran posisi
    - Monitor daily loss limit
    """

    def __init__(self):
        self.daily_loss    = 0.0
        self.daily_reset   = datetime.now(timezone.utc).date()
        self.open_trades   = 0

    def reset_daily_if_needed(self):
        today = datetime.now(timezone.utc).date()
        if today != self.daily_reset:
            self.daily_loss  = 0.0
            self.daily_reset = today

    def can_open_trade(self, balance: float) -> tuple[bool, str]:
        """Return (boleh, alasan jika tidak boleh)."""
        self.reset_daily_if_needed()

        if not config.BOT_ENABLED:
            return False, "Bot dinonaktifkan dari config"

        if self.daily_loss >= config.MAX_DAILY_LOSS:
            return False, f"Daily loss limit tercapai (${self.daily_loss:.2f} / ${config.MAX_DAILY_LOSS})"

        if balance < config.TRADE_SIZE_USDC:
            return False, f"Saldo tidak cukup (${balance:.2f} < ${config.TRADE_SIZE_USDC})"

        if self.open_trades >= 3:
            return False, "Terlalu banyak posisi terbuka (max 3)"

        return True, "OK"

    def record_loss(self, loss_usdc: float):
        """Tambahkan kerugian ke daily loss tracker."""
        self.reset_daily_if_needed()
        if loss_usdc > 0:
            self.daily_loss += loss_usdc

    def record_trade_opened(self):
        self.open_trades += 1

    def record_trade_closed(self):
        self.open_trades = max(0, self.open_trades - 1)

    def calculate_position_size(self, balance: float, price: float) -> float:
        """
        Hitung ukuran posisi (dalam koin) berdasarkan TRADE_SIZE_USDC dan leverage.
        Pastikan tidak melebihi 20% balance.
        """
        max_risk    = min(config.TRADE_SIZE_USDC, balance * 0.20)
        notional    = max_risk * config.LEVERAGE
        size_in_coin = notional / price
        return round(size_in_coin, 6)

    def calculate_tp_sl(self, entry_price: float, side: str) -> tuple[float, float]:
        """Return (take_profit_price, stop_loss_price)."""
        tp_pct = config.TAKE_PROFIT_PCT / 100
        sl_pct = config.STOP_LOSS_PCT   / 100

        if side == "LONG":
            tp = entry_price * (1 + tp_pct)
            sl = entry_price * (1 - sl_pct)
        else:
            tp = entry_price * (1 - tp_pct)
            sl = entry_price * (1 + sl_pct)

        return round(tp, 6), round(sl, 6)

    def should_close_position(
        self,
        current_price: float,
        entry_price: float,
        tp_price: float,
        sl_price: float,
        side: str,
    ) -> tuple[bool, str]:
        """Cek apakah posisi harus ditutup. Return (tutup, alasan)."""
        if side == "LONG":
            if current_price >= tp_price:
                return True, "TP"
            if current_price <= sl_price:
                return True, "SL"
        else:
            if current_price <= tp_price:
                return True, "TP"
            if current_price >= sl_price:
                return True, "SL"
        return False, ""

    def get_summary(self) -> dict:
        self.reset_daily_if_needed()
        return {
            "daily_loss":   round(self.daily_loss, 2),
            "daily_limit":  config.MAX_DAILY_LOSS,
            "open_trades":  self.open_trades,
            "bot_enabled":  config.BOT_ENABLED,
        }
