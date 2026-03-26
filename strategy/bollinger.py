import pandas as pd
from dataclasses import dataclass
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from strategy.personas import get_persona


@dataclass
class Signal:
    action: str           # BUY / SELL / HOLD
    reason: str
    entry_price: float
    tp_price: float
    sl_price: float
    bb_width: float
    adx: float
    market_condition: str  # ranging / trending / volatile
    persona_id: str


class BollingerStrategy:
    """
    Bollinger Band mean-reversion strategy.
    Parameter disesuaikan otomatis berdasarkan persona yang dipilih.
    """

    def __init__(self, persona_id: str = None):
        self.set_persona(persona_id or config.ACTIVE_PERSONA)

    def set_persona(self, persona_id: str):
        self.persona    = get_persona(persona_id)
        self.persona_id = persona_id
        self.period     = self.persona["bb_period"]
        self.std_dev    = self.persona["bb_std"]
        self.adx_limit  = self.persona["adx_max"]
        self.vol_spike  = self.persona["vol_spike"]
        self.confirm_n  = self.persona.get("confirm_candles", 1)
        self.prefer_long  = self.persona.get("prefer_long", False)
        self.prefer_short = self.persona.get("prefer_short", False)

    def analyze(self, candles: list) -> Signal:
        if len(candles) < self.period + 15:
            return self._hold("Data candle tidak cukup", candles[-1]["close"])

        df = pd.DataFrame(candles)
        df = self._calculate_indicators(df)

        last    = df.iloc[-1]
        close   = float(last["close"])
        high    = float(last["high"])
        low     = float(last["low"])
        upper   = float(last["bb_upper"])
        middle  = float(last["bb_middle"])
        lower   = float(last["bb_lower"])
        bb_width = float(last["bb_width"])
        adx     = float(last["adx"])

        market_condition = self._classify_market(df)

        # ── Breakout filter ───────────────────────────────────────────────────
        if market_condition != "ranging":
            return Signal(
                action="HOLD",
                reason=f"[{self.persona['name']}] Market {market_condition} - menunggu (ADX={adx:.1f})",
                entry_price=close, tp_price=close, sl_price=close,
                bb_width=bb_width, adx=adx,
                market_condition=market_condition,
                persona_id=self.persona_id,
            )

        # ── BUY signal ────────────────────────────────────────────────────────
        if not self.prefer_short and low <= lower and self._is_bullish_reversal(df):
            tp = close + (middle - close)
            sl = close * (1 - self.persona["sl_pct"] / 100)
            return Signal(
                action="BUY",
                reason=f"[{self.persona['name']}] Lower BB touch + bullish reversal",
                entry_price=close,
                tp_price=round(tp, 6),
                sl_price=round(sl, 6),
                bb_width=bb_width, adx=adx,
                market_condition=market_condition,
                persona_id=self.persona_id,
            )

        # ── SELL signal ───────────────────────────────────────────────────────
        if not self.prefer_long and high >= upper and self._is_bearish_reversal(df):
            tp = close - (close - middle)
            sl = close * (1 + self.persona["sl_pct"] / 100)
            return Signal(
                action="SELL",
                reason=f"[{self.persona['name']}] Upper BB touch + bearish reversal",
                entry_price=close,
                tp_price=round(tp, 6),
                sl_price=round(sl, 6),
                bb_width=bb_width, adx=adx,
                market_condition=market_condition,
                persona_id=self.persona_id,
            )

        return self._hold(
            f"[{self.persona['name']}] Menunggu setup yang tepat...",
            close, bb_width, adx, market_condition
        )

    # ── Indicators ────────────────────────────────────────────────────────────

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        close  = df["close"]
        volume = df["volume"]

        df["bb_middle"] = close.rolling(self.period).mean()
        rolling_std     = close.rolling(self.period).std()
        df["bb_upper"]  = df["bb_middle"] + (rolling_std * self.std_dev)
        df["bb_lower"]  = df["bb_middle"] - (rolling_std * self.std_dev)
        df["bb_width"]  = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
        df = self._calc_adx(df)
        df["volume_ma"]    = volume.rolling(20).mean()
        df["volume_ratio"] = volume / df["volume_ma"]
        return df

    def _calc_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        plus_dm  = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0]   = 0
        minus_dm[minus_dm < 0] = 0

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)

        atr      = tr.ewm(span=period, adjust=False).mean()
        plus_di  = 100 * (plus_dm.ewm(span=period, adjust=False).mean()  / atr)
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
        df["adx"] = dx.ewm(span=period, adjust=False).mean()
        return df

    def _classify_market(self, df: pd.DataFrame) -> str:
        last         = df.iloc[-1]
        adx          = float(last.get("adx", 0))
        bb_width_now = float(last["bb_width"])
        bb_width_avg = float(df["bb_width"].tail(50).mean())
        vol_ratio    = float(last.get("volume_ratio", 1.0))

        if adx > self.adx_limit or bb_width_now > bb_width_avg * 1.5 or vol_ratio > self.vol_spike:
            return "volatile" if (vol_ratio > self.vol_spike or bb_width_now > bb_width_avg * 1.5) else "trending"
        return "ranging"

    def _is_bullish_reversal(self, df: pd.DataFrame) -> bool:
        recent = df.tail(self.confirm_n + 1)
        last   = recent.iloc[-1]
        return float(last["close"]) > float(last["open"])

    def _is_bearish_reversal(self, df: pd.DataFrame) -> bool:
        recent = df.tail(self.confirm_n + 1)
        last   = recent.iloc[-1]
        return float(last["close"]) < float(last["open"])

    def _hold(self, reason, price, bb_width=0, adx=0, market_condition="unknown") -> Signal:
        return Signal(
            action="HOLD", reason=reason,
            entry_price=price, tp_price=price, sl_price=price,
            bb_width=bb_width, adx=adx,
            market_condition=market_condition,
            persona_id=self.persona_id,
        )
