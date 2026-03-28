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
import asyncio
import httpx
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

def _base_url() -> str:
    return config.BYBIT_BASE_URL.rstrip("/")
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


def _client(**kwargs) -> httpx.AsyncClient:
    """Buat httpx client, pakai proxy kalau BYBIT_PROXY diset."""
    proxy = config.BYBIT_PROXY
    if proxy:
        return httpx.AsyncClient(proxy=proxy, timeout=15, **kwargs)
    return httpx.AsyncClient(timeout=15, **kwargs)


def _parse_json(r: httpx.Response, context: str = "") -> dict:
    """Parse JSON response; return error dict on empty/invalid body."""
    import json as _json
    raw = r.text
    if not raw:
        msg = f"Empty response (HTTP {r.status_code})"
        print(f"[Bybit] {context} {msg}")
        return {"retCode": -1, "retMsg": msg, "result": {}}
    try:
        return r.json()
    except Exception:
        msg = f"Invalid JSON: {raw[:200]}"
        print(f"[Bybit] {context} {msg}")
        return {"retCode": -1, "retMsg": msg, "result": {}}


class BybitClient:

    # ── Balance ───────────────────────────────────────────────────────────────

    async def get_balance(self) -> dict:
        """
        Return {'USDT': float, 'USDC': float}
        Pakai accountType=UNIFIED (mendukung linear perp USDT & USDC).
        Retry 3x dengan jeda 2 detik kalau kena 403/timeout.
        """
        last_err = None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(2)
            try:
                ts  = str(int(time.time() * 1000))
                qs  = "accountType=UNIFIED"
                sig = _sign(config.BYBIT_API_SECRET, ts, qs)
                async with _client() as client:
                    r = await client.get(
                        f"{_base_url()}/v5/account/wallet-balance?{qs}",
                        headers=_headers(ts, sig),
                    )
                if r.status_code == 403:
                    last_err = RuntimeError("HTTP 403")
                    continue
                if not r.is_success:
                    raise RuntimeError(f"HTTP {r.status_code}")
                break
            except RuntimeError as e:
                last_err = e
                continue
            except Exception as e:
                last_err = e
                continue
        else:
            raise last_err or RuntimeError("get_balance gagal setelah 3 percobaan")
        data = _parse_json(r, "get_balance")
        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit error {data.get('retCode')}: {data.get('retMsg')}")
        result = {"USDT": 0.0, "USDC": 0.0, "total_usd": 0.0}
        for acct in data["result"].get("list", []):
            for coin in acct.get("coin", []):
                if coin["coin"] == "USDT":
                    result["USDT"] = float(coin.get("equity", 0))
                elif coin["coin"] == "USDC":
                    result["USDC"] = float(coin.get("equity", 0))
        result["total_usd"] = result["USDT"] + result["USDC"]
        return result

    # ── Positions ─────────────────────────────────────────────────────────────

    async def _fetch_positions_by_settle(self, settle_coin: str) -> list[dict]:
        """Fetch posisi untuk satu settle coin (USDT atau USDC)."""
        ts  = str(int(time.time() * 1000))
        qs  = f"category=linear&limit=50&settleCoin={settle_coin}"
        sig = _sign(config.BYBIT_API_SECRET, ts, qs)
        async with _client() as client:
            r = await client.get(
                f"{_base_url()}/v5/position/list?{qs}",
                headers=_headers(ts, sig),
            )
        if not r.is_success:
            raise RuntimeError(f"HTTP {r.status_code}")
        data = _parse_json(r, "_fetch_positions_by_settle")
        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit error {data.get('retCode')}: {data.get('retMsg')}")
        positions = []
        for p in data["result"].get("list", []):
            size = float(p.get("size", 0))
            if size == 0:
                continue
            entry = float(p.get("avgPrice", 0))
            mark  = float(p.get("markPrice", 0))
            upnl  = float(p.get("unrealisedPnl", 0))
            liq   = float(p.get("liqPrice", 0) or 0)
            sym   = p.get("symbol", "")
            positions.append({
                "symbol":         sym,
                "side":           p.get("side", ""),
                "size":           size,
                "entry_price":    entry,
                "mark_price":     mark,
                "unrealized_pnl": upnl,
                "pnl_pct":        round((upnl / (entry * size / float(p.get("leverage", 1)))) * 100, 2) if entry and size else 0,
                "leverage":       int(float(p.get("leverage", 1))),
                "liq_price":      liq,
                "tp_price":       float(p.get("takeProfit", 0) or 0),
                "sl_price":       float(p.get("stopLoss", 0) or 0),
                "settle":         settle_coin,
                "position_value": float(p.get("positionValue", 0)),
            })
        return positions

    async def get_positions(self, settle: str = "ALL") -> list[dict]:
        """
        Ambil semua posisi terbuka.
        settle='ALL': fetch USDT dan USDC secara terpisah lalu gabungkan.
        """
        if settle == "ALL":
            usdt = await self._fetch_positions_by_settle("USDT")
            usdc = await self._fetch_positions_by_settle("USDC")
            return usdt + usdc
        return await self._fetch_positions_by_settle(settle)

    # ── Position Mode ─────────────────────────────────────────────────────────

    async def _get_position_mode(self, symbol: str) -> str:
        """Return 'BothSide' (hedge) atau 'MergedSingle' (one-way).
        Coba detect dari posisi aktif; kalau kosong, coba query account info."""
        try:
            ts  = str(int(time.time() * 1000))
            qs  = f"category=linear&symbol={symbol}"
            sig = _sign(config.BYBIT_API_SECRET, ts, qs)
            async with _client() as client:
                r = await client.get(
                    f"{_base_url()}/v5/position/list?{qs}",
                    headers=_headers(ts, sig),
                )
            data  = _parse_json(r, "_get_position_mode")
            items = data.get("result", {}).get("list", [])
            if items:
                return items[0].get("positionMode", "MergedSingle")

            # Tidak ada posisi — coba query tanpa filter symbol untuk detect mode
            ts2  = str(int(time.time() * 1000))
            qs2  = "category=linear&settleCoin=USDT&limit=1"
            sig2 = _sign(config.BYBIT_API_SECRET, ts2, qs2)
            async with _client() as client:
                r2 = await client.get(
                    f"{_base_url()}/v5/position/list?{qs2}",
                    headers=_headers(ts2, sig2),
                )
            data2  = _parse_json(r2, "_get_position_mode2")
            items2 = data2.get("result", {}).get("list", [])
            if items2:
                return items2[0].get("positionMode", "BothSide")
        except Exception:
            pass
        return "BothSide"  # default hedge mode (lebih umum di akun futures)

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
        position_idx: int = None,  # None = auto-detect dari position mode
    ) -> dict:
        # Auto-detect positionIdx: hedge mode → Buy=1, Sell=2 | one-way → 0
        if position_idx is None:
            mode = await self._get_position_mode(symbol)
            if mode == "BothSide":  # hedge mode
                position_idx = 1 if side == "Buy" else 2
            else:
                position_idx = 0

        ts   = str(int(time.time() * 1000))
        body: dict = {
            "category":    "linear",
            "symbol":      symbol,
            "side":        side,
            "orderType":   order_type,
            "qty":         str(qty),
            "reduceOnly":  reduce_only,
            "positionIdx": position_idx,
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
        async with _client() as client:
            r = await client.post(
                f"{_base_url()}/v5/order/create",
                headers=_headers(ts, sig),
                content=payload,
            )
        raw = r.text
        if not raw:
            msg = f"Empty response from Bybit (HTTP {r.status_code}). CF Worker mungkin belum update."
            print(f"[Bybit] place_order error: {msg}")
            return {"retCode": -1, "retMsg": msg}
        try:
            data = r.json()
        except Exception:
            msg = f"Invalid JSON: {raw[:200]}"
            print(f"[Bybit] place_order error: {msg}")
            return {"retCode": -1, "retMsg": msg}
        if data.get("retCode") != 0:
            print(f"[Bybit] place_order error: {data.get('retMsg')}")
        return data

    async def close_position(self, symbol: str, side: str, size: float) -> dict:
        """Tutup posisi dengan market order reduce-only."""
        close_side = "Sell" if side == "Buy" else "Buy"
        # Untuk hedge mode: tutup long (Buy→positionIdx=1), tutup short (Sell→positionIdx=2)
        mode = await self._get_position_mode(symbol)
        if mode == "BothSide":
            pos_idx = 1 if side == "Buy" else 2  # sisi yang mau ditutup, bukan close_side
        else:
            pos_idx = 0
        return await self.place_order(symbol, close_side, size, reduce_only=True, position_idx=pos_idx)

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
        async with _client() as client:
            r = await client.post(
                f"{_base_url()}/v5/position/trading-stop",
                headers=_headers(ts, sig),
                content=payload,
            )
            return _parse_json(r, "set_tp_sl")

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
        async with _client() as client:
            r = await client.post(
                f"{_base_url()}/v5/position/set-leverage",
                headers=_headers(ts, sig),
                content=payload,
            )
            return _parse_json(r, "set_leverage")

    # ── Candles ───────────────────────────────────────────────────────────────

    async def get_candles(self, symbol: str, interval: str = "60", limit: int = 200) -> list:
        """
        interval: '1','3','5','15','30','60','120','240','D','W'
        Return list of [time, open, high, low, close, volume]
        """
        qs  = f"category=linear&symbol={symbol}&interval={interval}&limit={limit}"
        async with _client() as client:
            r = await client.get(f"{_base_url()}/v5/market/kline?{qs}")
            data = _parse_json(r, "get_candles")
        if data.get("retCode") != 0:
            return []
        return data["result"].get("list", [])

    # ── Ticker ────────────────────────────────────────────────────────────────

    async def get_tickers(self, symbols: list[str] = None) -> dict:
        """Return {symbol: {mark_price, index_price, funding_rate, ...}}
        Public endpoint — no auth required."""
        qs  = "category=linear"
        if symbols and len(symbols) == 1:
            qs += f"&symbol={symbols[0]}"
        async with _client() as client:
            r = await client.get(f"{_base_url()}/v5/market/tickers?{qs}")
            data = _parse_json(r, "get_tickers")
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
