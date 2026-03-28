"""
Polymarket CLOB Client
======================
Mendukung:
- Gamma API (public): market data, popular markets, positions by wallet
- CLOB API (authenticated): balance, order placement

Autentikasi: API Key + Secret + Passphrase (derived from private key)
"""
import httpx
import time
import json
import hmac
import hashlib
import base64
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL  = "https://clob.polymarket.com"


class PolymarketClient:

    def is_configured(self) -> bool:
        return bool(config.POLY_WALLET_ADDRESS)

    def is_trading_configured(self) -> bool:
        return bool(config.POLY_API_KEY and config.POLY_API_SECRET and config.POLY_API_PASSPHRASE)

    # ── Auth headers ──────────────────────────────────────────────────────────

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict:
        """Generate L2 auth headers for CLOB API."""
        ts        = str(int(time.time() * 1000))
        msg       = ts + method.upper() + path + body
        secret_b  = base64.b64decode(config.POLY_API_SECRET + "==")
        sig       = base64.b64encode(hmac.new(secret_b, msg.encode(), hashlib.sha256).digest()).decode()
        return {
            "POLY-API-KEY":        config.POLY_API_KEY,
            "POLY-TIMESTAMP":      ts,
            "POLY-SIGNATURE":      sig,
            "POLY-PASSPHRASE":     config.POLY_API_PASSPHRASE,
            "Content-Type":        "application/json",
        }

    # ── Public market data ────────────────────────────────────────────────────

    async def get_popular_markets(self, limit: int = 20) -> list:
        """Ambil market populer berdasarkan volume 24h."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{GAMMA_URL}/markets", params={
                "active":    "true",
                "closed":    "false",
                "order":     "volume24hr",
                "ascending": "false",
                "limit":     limit,
            })
        markets = r.json() if r.is_success else []
        result = []
        for m in markets:
            tokens    = m.get("tokens", [])
            yes_price = 0.0
            no_price  = 0.0
            yes_token_id = ""
            no_token_id  = ""
            for t in tokens:
                if t.get("outcome", "").lower() == "yes":
                    yes_price    = float(t.get("price", 0) or 0)
                    yes_token_id = t.get("token_id", "")
                elif t.get("outcome", "").lower() == "no":
                    no_price    = float(t.get("price", 0) or 0)
                    no_token_id = t.get("token_id", "")
            result.append({
                "id":           m.get("id", ""),
                "condition_id": m.get("conditionId", ""),
                "question":     m.get("question", ""),
                "category":     m.get("groupItemTitle") or m.get("category", ""),
                "yes_price":    round(yes_price * 100, 1),   # dalam %
                "no_price":     round(no_price * 100, 1),
                "yes_token_id": yes_token_id,
                "no_token_id":  no_token_id,
                "volume_24h":   float(m.get("volume24hr", 0) or 0),
                "volume_total": float(m.get("volume", 0) or 0),
                "liquidity":    float(m.get("liquidity", 0) or 0),
                "end_date":     (m.get("endDate", "") or "")[:10],
            })
        return result

    # ── Positions ─────────────────────────────────────────────────────────────

    async def get_positions(self) -> list:
        """Ambil posisi aktif berdasarkan wallet address."""
        if not config.POLY_WALLET_ADDRESS:
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{GAMMA_URL}/positions", params={
                    "user":          config.POLY_WALLET_ADDRESS,
                    "sizeThreshold": "0.01",
                })
            if not r.is_success:
                return []
            positions = r.json()
            if not isinstance(positions, list):
                positions = positions.get("data", []) if isinstance(positions, dict) else []
            result = []
            for p in positions:
                market = p.get("market") or {}
                result.append({
                    "market":        market.get("question", p.get("title", "")),
                    "outcome":       p.get("outcome", ""),
                    "size":          float(p.get("size", 0) or 0),
                    "avg_price":     round(float(p.get("avgPrice", 0) or 0) * 100, 1),
                    "current_price": round(float(p.get("currentPrice", 0) or 0) * 100, 1),
                    "value":         float(p.get("value", 0) or 0),
                    "pnl":           float(p.get("cashBalance", 0) or 0),
                })
            return result
        except Exception as e:
            print(f"[Polymarket] positions error: {e}")
            return []

    # ── Balance ───────────────────────────────────────────────────────────────

    async def get_balance(self) -> dict:
        """Ambil USDC balance dari CLOB API."""
        if not self.is_trading_configured():
            return {"usdc": 0.0, "error": "API key belum dikonfigurasi"}
        try:
            path = "/balance"
            headers = self._auth_headers("GET", path)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{CLOB_URL}{path}", headers=headers)
            if not r.is_success:
                return {"usdc": 0.0, "error": f"HTTP {r.status_code}"}
            data = r.json()
            return {"usdc": float(data.get("balance", 0))}
        except Exception as e:
            return {"usdc": 0.0, "error": str(e)}

    # ── Place order ───────────────────────────────────────────────────────────

    async def place_order(self, token_id: str, side: str, price: float, size: float) -> dict:
        """
        Place limit order di CLOB.
        side: 'buy' atau 'sell'
        price: 0.0-1.0 (bukan %)
        size: jumlah USDC
        """
        if not self.is_trading_configured():
            return {"error": "API key belum dikonfigurasi"}
        try:
            path    = "/order"
            body_d  = {
                "tokenID":   token_id,
                "side":      side.upper(),
                "price":     str(price),
                "size":      str(size),
                "orderType": "GTC",
                "feeRateBps": "0",
            }
            body    = json.dumps(body_d)
            headers = self._auth_headers("POST", path, body)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(f"{CLOB_URL}{path}", headers=headers, content=body)
            return r.json()
        except Exception as e:
            return {"error": str(e)}
