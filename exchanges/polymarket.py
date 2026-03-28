"""
Polymarket CLOB Client
======================
Mendukung:
- Gamma API (public): market data, popular markets, positions by wallet
- CLOB API (L1 auth via private key): balance, order placement

Autentikasi L1: sign setiap request pakai ETH private key (eth-account).
Tidak perlu API key/secret/passphrase terpisah.
Cukup set: POLY_WALLET_ADDRESS + POLY_PRIVATE_KEY
"""
import httpx
import time
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    _ETH_AVAILABLE = True
except ImportError:
    _ETH_AVAILABLE = False

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL  = "https://clob.polymarket.com"


class PolymarketClient:

    def is_configured(self) -> bool:
        return bool(config.POLY_WALLET_ADDRESS)

    def is_trading_configured(self) -> bool:
        return bool(config.POLY_PRIVATE_KEY and config.POLY_WALLET_ADDRESS and _ETH_AVAILABLE)

    # ── L1 Auth headers (sign with private key) ───────────────────────────────

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict:
        """Generate L1 auth headers for CLOB API using ETH private key."""
        ts  = str(int(time.time()))
        msg = ts + method.upper() + path + body
        message = encode_defunct(text=msg)
        signed  = Account.sign_message(message, private_key=config.POLY_PRIVATE_KEY)
        sig     = signed.signature.hex()
        return {
            "POLY-ADDRESS":   config.POLY_WALLET_ADDRESS,
            "POLY-TIMESTAMP": ts,
            "POLY-SIGNATURE": sig,
            "Content-Type":   "application/json",
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

            # Token IDs from tokens array (by name first, then by index)
            for t in tokens:
                outcome_name = t.get("outcome", "").lower()
                if outcome_name == "yes":
                    yes_token_id = t.get("token_id", "")
                    yes_price    = float(t.get("price", 0) or 0)
                elif outcome_name == "no":
                    no_token_id  = t.get("token_id", "")
                    no_price     = float(t.get("price", 0) or 0)
            # Fallback by index for sports/non-binary markets
            if not yes_token_id and len(tokens) > 0:
                yes_token_id = tokens[0].get("token_id", "")
            if not no_token_id and len(tokens) > 1:
                no_token_id = tokens[1].get("token_id", "")

            # Gamma API stores prices in outcomePrices as JSON string
            # e.g. outcomePrices='["0.95","0.05"]', outcomes='["Yes","No"]'
            # For sports markets outcomes can be team names, not yes/no
            yes_label = "YES"
            no_label  = "NO"
            try:
                raw_prices   = m.get("outcomePrices", "[]")
                raw_outcomes = m.get("outcomes", "[]")
                prices_list   = json.loads(raw_prices)   if isinstance(raw_prices, str)   else (raw_prices or [])
                outcomes_list = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else (raw_outcomes or [])

                for idx, oc in enumerate(outcomes_list):
                    if idx < len(prices_list):
                        p = float(prices_list[idx] or 0)
                        if oc.lower() == "yes":
                            yes_price = p
                        elif oc.lower() == "no":
                            no_price = p

                # If still 0 (sports/non-binary), use first two outcomes
                if yes_price == 0 and no_price == 0 and len(outcomes_list) >= 2:
                    yes_price = float(prices_list[0] or 0) if len(prices_list) > 0 else 0
                    no_price  = float(prices_list[1] or 0) if len(prices_list) > 1 else 0
                    yes_label = outcomes_list[0][:12]  # potong bila terlalu panjang
                    no_label  = outcomes_list[1][:12]
            except Exception:
                pass

            result.append({
                "id":           m.get("id", ""),
                "condition_id": m.get("conditionId", ""),
                "question":     m.get("question", ""),
                "category":     m.get("groupItemTitle") or m.get("category", ""),
                "yes_price":    round(yes_price * 100, 1),   # dalam %
                "no_price":     round(no_price * 100, 1),
                "yes_label":    yes_label,
                "no_label":     no_label,
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
            return {"usdc": 0.0, "error": "Private key belum dikonfigurasi (set POLY_PRIVATE_KEY)"}
        try:
            path    = "/balance"
            headers = self._auth_headers("GET", path)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{CLOB_URL}{path}", headers=headers)
            if not r.is_success:
                return {"usdc": 0.0, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
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
            return {"error": "Private key belum dikonfigurasi (set POLY_PRIVATE_KEY)"}
        try:
            path   = "/order"
            body_d = {
                "tokenID":    token_id,
                "side":       side.upper(),
                "price":      str(price),
                "size":       str(size),
                "orderType":  "GTC",
                "feeRateBps": "0",
            }
            body    = json.dumps(body_d)
            headers = self._auth_headers("POST", path, body)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(f"{CLOB_URL}{path}", headers=headers, content=body)
            return r.json()
        except Exception as e:
            return {"error": str(e)}
