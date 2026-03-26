import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


@dataclass
class Signal:
    action: str          # BUY / SELL / HOLD
    reason: str
    entry_price: float
    tp_price: float
    sl_price: float
    bb_width: float
    adx: float
    market_condition: str  # ranging / trending / volatile


class BollingerStrategy:
    """
    Mean-reversion Bollinger Band dengan breakout filter.

    Logika:
    - Entry LONG  : harga menyentuh lower BB + konfirmasi bullish candle
                    + market RANGING (ADX < threshold, BB width normal, volume normal)
    - Entry SHORT : harga menyentuh upper BB + konfirmasi bearish candle
                    + market RANGING
    - Skip        : breakout terdeteksi (ADX tinggi / BB melebar tiba2 / volume spike)
    """

    def __init__(self):
        self.period    = config.BB_PERIOD
        self.std_dev   = config.BB_STD
        self.adx_limit = config.ADX_THRESHOLD
        self.vol_spike = config.VOLUME_SPIKE_X

    def analyze(self, candles: list) -> Signal:
        if len(candles) < self.period + 10:
            return self._hold("Data candle tidak cukup", candles[-1]["close"])

        df = pd.DataFrame(candles)
        df = self._calculate_indicators(df)

        last    = df.iloc[-1]
        prev    = df.iloc[-2]
        close   = float(last["close"])
        high    = float(last["high"])
        low     = float(last["low"])

        upper   = float(last["bb_upper"])
        middle  = float(last["bb_middle"])
        lower   = float(last["bb_lower"])
        bb_width = float(last["bb_width"])
        adx     = float(last["adx"])

        market_condition = self._classify_market(df)

        # ── Breakout filter: jangan trade kalau market bukan ranging ──────────
        if market_condition != "ranging":
            return Signal(
                action="HOLD",
                reason=f"Market {market_condition} - skip trading (ADX={adx:.1f})",
                entry_price=close,
                tp_price=close,
                sl_price=close,
                bb_width=bb_width,
                adx=adx,
                market_condition=market_condition,
            )

        # ── BUY signal: harga sentuh / lewati lower BB + reversal ────────────
        if low <= lower and self._is_bullish_reversal(df):
            tp = close + (middle - close) * 1.0    # target ke middle BB
            sl = close * (1 - config.STOP_LOSS_PCT / 100)
            return Signal(
                action="BUY",
                reason=f"Harga sentuh Lower BB ({lower:.4f}), bullish reversal, market ranging",
                entry_price=close,
                tp_price=round(tp, 6),
                sl_price=round(sl, 6),
                bb_width=bb_width,
                adx=adx,
                market_condition=market_condition,
            )

        # ── SELL signal: harga sentuh / lewati upper BB + reversal ───────────
        if high >= upper and self._is_bearish_reversal(df):
            tp = close - (close - middle) * 1.0    # target ke middle BB
            sl = close * (1 + config.STOP_LOSS_PCT / 100)
            return Signal(
                action="SELL",
                reason=f"Harga sentuh Upper BB ({upper:.4f}), bearish reversal, market ranging",
                entry_price=close,
                tp_price=round(tp, 6),
                sl_price=round(sl, 6),
                bb_width=bb_width,
                adx=adx,
                market_condition=market_condition,
            )

        return self._hold(
            f"Tidak ada signal (harga di dalam BB, ADX={adx:.1f})",
            close, bb_width, adx, market_condition
        )

    # ── Indicator calculations ────────────────────────────────────────────────

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        volume = df["volume"]

        # Bollinger Bands
        df["bb_middle"] = close.rolling(self.period).mean()
        rolling_std      = close.rolling(self.period).std()
        df["bb_upper"]  = df["bb_middle"] + (rolling_std * self.std_dev)
        df["bb_lower"]  = df["bb_middle"] - (rolling_std * self.std_dev)
        df["bb_width"]  = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]

        # ADX (Average Directional Index)
        df = self._calc_adx(df)

        # Volume MA
        df["volume_ma"] = volume.rolling(20).mean()
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

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
        df["adx"]      = dx.ewm(span=period, adjust=False).mean()
        df["plus_di"]  = plus_di
        df["minus_di"] = minus_di
        return df

    # ── Market classifier ─────────────────────────────────────────────────────

    def _classify_market(self, df: pd.DataFrame) -> str:
        last = df.iloc[-1]
        adx  = float(last.get("adx", 0))

        # BB width dibanding rata-rata 50 candle terakhir
        bb_width_now = float(last["bb_width"])
        bb_width_avg = float(df["bb_width"].tail(50).mean())
        bb_expanding = bb_width_now > bb_width_avg * 1.5

        # Volume spike
        vol_ratio = float(last.get("volume_ratio", 1.0))
        vol_spike  = vol_ratio > self.vol_spike

        if adx > self.adx_limit or bb_expanding or vol_spike:
            if vol_spike or bb_expanding:
                return "volatile"
            return "trending"
        return "ranging"

    # ── Reversal confirmation ─────────────────────────────────────────────────

    def _is_bullish_reversal(self, df: pd.DataFrame) -> bool:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        # Candle close di atas open (bullish body)
        bullish_candle = float(last["close"]) > float(last["open"])
        # Candle sebelumnya bearish
        prev_bearish   = float(prev["close"]) < float(prev["open"])
        return bullish_candle and prev_bearish

    def _is_bearish_reversal(self, df: pd.DataFrame) -> bool:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        bearish_candle = float(last["close"]) < float(last["open"])
        prev_bullish   = float(prev["close"]) > float(prev["open"])
        return bearish_candle and prev_bullish

    def _hold(
        self, reason: str, price: float,
        bb_width: float = 0, adx: float = 0,
        market_condition: str = "unknown"
    ) -> Signal:
        return Signal(
            action="HOLD",
            reason=reason,
            entry_price=price,
            tp_price=price,
            sl_price=price,
            bb_width=bb_width,
            adx=adx,
            market_condition=market_condition,
        )
