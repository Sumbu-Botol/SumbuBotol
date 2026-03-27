"""
Bybit V5 REST API Client
========================
Mendukung:
- USDT Perpetual  (category=linear, symbol=BTCUSDT)
- USDC Perpetual  (category=linear, symbol=BTCPERP / settle=USDC)

Autentikasi: HMAC-SHA256, parameter di query string (GET) atau body JSON (POST).
"""
import hashlib
import hmac
import time
import httpx
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

BASE_URL = "https://api.bybit.com"
RECV_WINDOW = "5000"


def _sign(api_secret: str, timestamp: str, payload: str) -> str:
    msg = timestamp + config.BYBIT_API_KEY + RECV_WINDOW + payload
    return hmac.new(api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _headers(timestamp: str, signature: str) -> dict:
    return {
        "X-BAPI-API-KEY":     config.BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP":   timestamp,
        "X-BAPI-SIGN":        signature,
        "X-BAPI-RECV-WINDOW": RECV_WINDOW,
        "Content-Type":       "application/json",
    }


class BybitClient:

    # ── Balance ───────────────────────────────────────────────────────────────

    async def get_balance(self) -> dict:
        """
        Return {'USDT': float, 'USDC': float}
        Pakai accountType=UNIFIED (mendukung linear perp USDT & USDC).
        """
        ts  = str(int(time.time() * 1000))
        qs  = "accountType=UNIFIED"
        sig = _sign(config.BYBIT_API_SECRET, ts, qs)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/v5/account/wallet-balance?{qs}",
                headers=_headers(ts, sig),
            )
            data = r.json()
        result = {"USDT": 0.0, "USDC": 0.0, "total_usd": 0.0}
        if data.get("retCode") != 0:
            print(f"[Bybit] get_balance error: {data.get('retMsg')}")
            return result
        for acct in data["result"].get("list", []):
            for coin in acct.get("coin", []):
                if coin["coin"] == "USDT":
                    result["USDT"] = float(coin.get("walletBalance", 0))
                elif coin["coin"] == "USDC":
                    result["USDC"] = float(coin.get("walletBalance", 0))
        result["total_usd"] = result["USDT"] + result["USDC"]
        return result

    # ── Positions ─────────────────────────────────────────────────────────────

    async def get_positions(self, settle: str = "ALL") -> list[dict]:
        """
        Ambil semua posisi terbuka (USDT + USDC perpetual).
        settle: 'ALL' | 'USDT' | 'USDC'
        """
        ts  = str(int(time.time() * 1000))
        qs  = "category=linear&limit=50"
        if settle != "ALL":
            qs += f"&settleCoin={settle}"
        sig = _sign(config.BYBIT_API_SECRET, ts, qs)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/v5/position/list?{qs}",
                headers=_headers(ts, sig),
            )
            data = r.json()
        positions = []
        if data.get("retCode") != 0:
            print(f"[Bybit] get_positions error: {data.get('retMsg')}")
            return positions
        for p in data["result"].get("list", []):
            size = float(p.get("size", 0))
            if size == 0:
                continue
            entry  = float(p.get("avgPrice", 0))
            mark   = float(p.get("markPrice", 0))
            upnl   = float(p.get("unrealisedPnl", 0))
            liq    = float(p.get("liqPrice", 0) or 0)
            # Deteksi settle coin dari symbol
            sym = p.get("symbol", "")
            settle_coin = "USDC" if (sym.endswith("PERP") or sym.endswith("USDC")) else "USDT"
            positions.append({
                "symbol":        sym,
                "side":          p.get("side", ""),          # Buy / Sell
                "size":          size,
                "entry_price":   entry,
                "mark_price":    mark,
                "unrealized_pnl": upnl,
                "pnl_pct":       round((upnl / (entry * size / float(p.get("leverage", 1)))) * 100, 2) if entry and size else 0,
                "leverage":      int(float(p.get("leverage", 1))),
                "liq_price":     liq,
                "tp_price":      float(p.get("takeProfit", 0) or 0),
                "sl_price":      float(p.get("stopLoss", 0) or 0),
                "settle":        settle_coin,
                "position_value": float(p.get("positionValue", 0)),
            })
        return positions

    # ── Orders ────────────────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,          # Buy / Sell
        qty: float,
        order_type: str = "Market",
        price: float = None,
        tp: float = None,
        sl: float = None,
        reduce_only: bool = False,
    ) -> dict:
        ts   = str(int(time.time() * 1000))
        body: dict = {
            "category":  "linear",
            "symbol":    symbol,
            "side":      side,
            "orderType": order_type,
            "qty":       str(qty),
            "reduceOnly": reduce_only,
            "timeInForce": "GTC" if order_type == "Limit" else "IOC",
        }
        if price and order_type == "Limit":
            body["price"] = str(price)
        if tp:
            body["takeProfit"] = str(tp)
        if sl:
            body["stopLoss"] = str(sl)

        import json
        payload = json.dumps(body)
        sig = _sign(config.BYBIT_API_SECRET, ts, payload)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{BASE_URL}/v5/order/create",
                headers=_headers(ts, sig),
                content=payload,
            )
            data = r.json()
        if data.get("retCode") != 0:
            print(f"[Bybit] place_order error: {data.get('retMsg')}")
        return data

    async def close_position(self, symbol: str, side: str, size: float) -> dict:
        """Tutup posisi dengan market order reduce-only."""
        close_side = "Sell" if side == "Buy" else "Buy"
        return await self.place_order(symbol, close_side, size, reduce_only=True)

    async def close_all_positions(self) -> list:
        positions = await self.get_positions()
        results = []
        for p in positions:
            r = await self.close_position(p["symbol"], p["side"], p["size"])
            results.append(r)
        return results

    # ── TP / SL ───────────────────────────────────────────────────────────────

    async def set_tp_sl(
        self,
        symbol: str,
        tp: float = None,
        sl: float = None,
        position_idx: int = 0,
    ) -> dict:
        ts   = str(int(time.time() * 1000))
        body: dict = {
            "category":    "linear",
            "symbol":      symbol,
            "positionIdx": position_idx,
        }
        if tp:
            body["takeProfit"] = str(tp)
        if sl:
            body["stopLoss"] = str(sl)
        import json
        payload = json.dumps(body)
        sig = _sign(config.BYBIT_API_SECRET, ts, payload)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{BASE_URL}/v5/position/trading-stop",
                headers=_headers(ts, sig),
                content=payload,
            )
            return r.json()

    # ── Leverage ──────────────────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        ts   = str(int(time.time() * 1000))
        import json
        body = {
            "category":     "linear",
            "symbol":       symbol,
            "buyLeverage":  str(leverage),
            "sellLeverage": str(leverage),
        }
        payload = json.dumps(body)
        sig = _sign(config.BYBIT_API_SECRET, ts, payload)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{BASE_URL}/v5/position/set-leverage",
                headers=_headers(ts, sig),
                content=payload,
            )
            return r.json()

    # ── Candles ───────────────────────────────────────────────────────────────

    async def get_candles(self, symbol: str, interval: str = "60", limit: int = 200) -> list:
        """
        interval: '1','3','5','15','30','60','120','240','D','W'
        Return list of [time, open, high, low, close, volume]
        """
        qs  = f"category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        ts  = str(int(time.time() * 1000))
        sig = _sign(config.BYBIT_API_SECRET, ts, qs)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/v5/market/kline?{qs}",
                headers=_headers(ts, sig),
            )
            data = r.json()
        if data.get("retCode") != 0:
            return []
        return data["result"].get("list", [])

    # ── Ticker ────────────────────────────────────────────────────────────────

    async def get_tickers(self, symbols: list[str] = None) -> dict:
        """Return {symbol: {mark_price, index_price, funding_rate, ...}}"""
        qs  = "category=linear"
        if symbols and len(symbols) == 1:
            qs += f"&symbol={symbols[0]}"
        ts  = str(int(time.time() * 1000))
        sig = _sign(config.BYBIT_API_SECRET, ts, qs)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/v5/market/tickers?{qs}",
                headers=_headers(ts, sig),
            )
            data = r.json()
        result = {}
        for t in data.get("result", {}).get("list", []):
            result[t["symbol"]] = {
                "mark_price":   float(t.get("markPrice", 0)),
                "index_price":  float(t.get("indexPrice", 0)),
                "last_price":   float(t.get("lastPrice", 0)),
                "funding_rate": float(t.get("fundingRate", 0)),
                "volume_24h":   float(t.get("volume24h", 0)),
            }
        return result
