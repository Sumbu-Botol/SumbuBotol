"""
Polymarket CLOB Client
======================
Mendukung:
- Gamma API (public): market data, popular markets, positions by wallet
- CLOB API (py-clob-client): balance, order placement dengan EIP-712 signing

Order placement pakai py-clob-client (library resmi Polymarket) yang handle:
- EIP-712 order signing
- L1 auth untuk buat API key
- L2 auth (HMAC) untuk kirim order
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

try:
    from py_clob_client.client import ClobClient as _ClobClient
    from py_clob_client.clob_types import OrderArgs as _OrderArgs, OrderType as _OrderType
    _CLOB_CLIENT_AVAILABLE = True
except ImportError:
    _CLOB_CLIENT_AVAILABLE = False

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL  = "https://clob.polymarket.com"
_POLYGON_CHAIN_ID = 137


def _client(**kwargs) -> httpx.AsyncClient:
    """Buat httpx client, pakai proxy POLY_PROXY kalau diset."""
    kwargs.setdefault("timeout", 15)
    proxy = getattr(config, "POLY_PROXY", "") or ""
    if proxy:
        return httpx.AsyncClient(proxy=proxy, **kwargs)
    return httpx.AsyncClient(**kwargs)


def _get_proxy() -> str:
    return getattr(config, "POLY_PROXY", "") or ""


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

    async def _fetch_clob_tokens(self, client: httpx.AsyncClient, condition_id: str) -> list:
        """Fetch token IDs from CLOB API for a given conditionId."""
        try:
            r = await client.get(f"{CLOB_URL}/markets/{condition_id}", timeout=10)
            if r.is_success:
                return r.json().get("tokens", [])
        except Exception:
            pass
        return []

    async def get_popular_markets(self, limit: int = 20) -> list:
        """Ambil market populer berdasarkan volume 24h."""
        async with _client(timeout=20) as client:
            r = await client.get(f"{GAMMA_URL}/markets", params={
                "active":    "true",
                "closed":    "false",
                "order":     "volume24hr",
                "ascending": "false",
                "limit":     limit,
            })
            markets = r.json() if r.is_success else []

            # Fetch token IDs from CLOB API concurrently for all markets
            import asyncio as _aio
            clob_tokens_list = await _aio.gather(*[
                self._fetch_clob_tokens(client, m.get("conditionId", ""))
                for m in markets
            ])

        result = []
        for m, clob_tokens in zip(markets, clob_tokens_list):
            yes_price    = 0.0
            no_price     = 0.0
            yes_token_id = ""
            no_token_id  = ""
            yes_label    = "YES"
            no_label     = "NO"

            # Parse prices and labels from Gamma API outcomePrices/outcomes
            try:
                raw_prices   = m.get("outcomePrices", "[]")
                raw_outcomes = m.get("outcomes", "[]")
                prices_list   = json.loads(raw_prices)   if isinstance(raw_prices, str)   else (raw_prices or [])
                outcomes_list = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else (raw_outcomes or [])

                if len(outcomes_list) >= 2:
                    yes_price = float(prices_list[0] or 0) if len(prices_list) > 0 else 0
                    no_price  = float(prices_list[1] or 0) if len(prices_list) > 1 else 0
                    lbl0 = outcomes_list[0]
                    lbl1 = outcomes_list[1]
                    yes_label = lbl0 if lbl0.lower() != "yes" else "YES"
                    no_label  = lbl1 if lbl1.lower() != "no"  else "NO"
                    # Truncate long team names
                    if len(yes_label) > 14:
                        yes_label = yes_label[:13] + "…"
                    if len(no_label) > 14:
                        no_label = no_label[:13] + "…"
            except Exception:
                pass

            # Get token IDs from CLOB API response
            for t in clob_tokens:
                outcome_name = t.get("outcome", "").lower()
                tid          = t.get("token_id", "")
                if outcome_name == outcomes_list[0].lower() if 'outcomes_list' in dir() and outcomes_list else outcome_name == "yes":
                    yes_token_id = tid
                elif outcome_name == outcomes_list[1].lower() if 'outcomes_list' in dir() and outcomes_list else outcome_name == "no":
                    no_token_id = tid
            # Fallback by index
            if not yes_token_id and len(clob_tokens) > 0:
                yes_token_id = clob_tokens[0].get("token_id", "")
            if not no_token_id and len(clob_tokens) > 1:
                no_token_id = clob_tokens[1].get("token_id", "")

            result.append({
                "id":           m.get("id", ""),
                "condition_id": m.get("conditionId", ""),
                "question":     m.get("question", ""),
                "category":     m.get("groupItemTitle") or m.get("category", ""),
                "yes_price":    round(yes_price * 100, 1),
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
        """Ambil posisi aktif — cek kedua wallet (EOA dan proxy)."""
        wallets = list({config.POLY_PROXY_ADDRESS, config.POLY_WALLET_ADDRESS} - {""})
        if not wallets:
            return []
        result = []
        try:
            async with _client() as client:
                for wallet in wallets:
                    r = await client.get(f"{GAMMA_URL}/positions", params={
                        "user":          wallet,
                        "sizeThreshold": "0.01",
                    })
                    if not r.is_success:
                        continue
                    positions = r.json()
                    if not isinstance(positions, list):
                        positions = positions.get("data", []) if isinstance(positions, dict) else []
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
        """Ambil USDC balance via CLOB API (authenticated) untuk EOA dan proxy wallet."""
        if not self.is_trading_configured() or not _CLOB_CLIENT_AVAILABLE:
            return {"usdc": 0.0, "error": "Not configured"}
        proxy = _get_proxy()

        def _sync():
            if proxy:
                try:
                    import py_clob_client.http_helpers.helpers as _h
                    _h._http_client = httpx.Client(proxy=proxy, timeout=15)
                except Exception:
                    pass
            results = {}
            for label, sig_type, funder in [
                ("eoa",   0, config.POLY_WALLET_ADDRESS),
                ("proxy", 1, config.POLY_PROXY_ADDRESS),
            ]:
                if not funder:
                    continue
                try:
                    c = _ClobClient(
                        host=CLOB_URL,
                        key=config.POLY_PRIVATE_KEY,
                        chain_id=_POLYGON_CHAIN_ID,
                        signature_type=sig_type,
                        funder=funder,
                    )
                    try:
                        creds = c.create_api_key()
                    except Exception:
                        creds = c.derive_api_key()
                    c.set_api_creds(creds)
                    try:
                        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                        bal = c.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.USDC))
                    except Exception:
                        from py_clob_client.clob_types import BalanceAllowanceParams
                        bal = c.get_balance_allowance(BalanceAllowanceParams(asset_type=0))
                    raw = bal.get("balance", bal.get("allowance", 0)) if isinstance(bal, dict) else 0
                    usdc = float(raw or 0) / 1e6
                    results[label] = {"address": funder[:10] + "...", "usdc": usdc}
                except Exception as e:
                    results[label] = {"address": funder[:10] + "...", "usdc": 0.0, "error": str(e)[:80]}
            return results

        import asyncio
        loop = asyncio.get_running_loop()
        detail = await loop.run_in_executor(None, _sync)
        usdc = max((v.get("usdc", 0) for v in detail.values()), default=0.0)
        return {"usdc": usdc, "detail": detail}

    # ── Place order (via py-clob-client) ──────────────────────────────────────

    async def test_auth(self) -> dict:
        """Test autentikasi: buat API key via L1, cek apakah wallet terdaftar di CLOB."""
        if not self.is_trading_configured():
            return {"error": "Private key belum dikonfigurasi"}
        if not _CLOB_CLIENT_AVAILABLE:
            return {"error": "py-clob-client tidak terinstall"}
        import asyncio
        proxy = _get_proxy()

        def _sync():
            if proxy:
                try:
                    import py_clob_client.http_helpers.helpers as _h
                    _h._http_client = httpx.Client(proxy=proxy, timeout=15)
                except Exception:
                    pass
            try:
                client = _ClobClient(
                    host=CLOB_URL,
                    key=config.POLY_PRIVATE_KEY,
                    chain_id=_POLYGON_CHAIN_ID,
                    signature_type=1 if config.POLY_PROXY_ADDRESS else 0,
                    funder=config.POLY_PROXY_ADDRESS or config.POLY_WALLET_ADDRESS,
                )
                # Try create_api_key explicitly to detect if it falls back to derive
                try:
                    creds = client.create_api_key()
                    creds_source = "created"
                except Exception as ce:
                    creds = client.derive_api_key()
                    creds_source = f"derived (create failed: {str(ce)[:80]})"
                client.set_api_creds(creds)
                return {
                    "ok":          True,
                    "api_key":     creds.api_key[:8] + "…" if hasattr(creds, "api_key") else str(creds)[:30],
                    "creds_source": creds_source,
                    "signer":      client.get_address(),
                    "funder":      config.POLY_PROXY_ADDRESS or config.POLY_WALLET_ADDRESS,
                    "proxy_used":  bool(proxy),
                }
            except Exception as e:
                return {"ok": False, "error": str(e), "proxy_used": bool(proxy)}

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync)

    async def place_order(self, token_id: str, side: str, price: float, size: float) -> dict:
        """
        Place limit order di CLOB via py-clob-client (handles EIP-712 signing).
        side: 'BUY' atau 'SELL'
        price: 0.0-1.0 (bukan %)
        size: jumlah USDC
        """
        if not self.is_trading_configured():
            return {"error": "Private key belum dikonfigurasi (set POLY_PRIVATE_KEY)"}
        if not _CLOB_CLIENT_AVAILABLE:
            return {"error": "py-clob-client tidak terinstall. Tambahkan ke requirements.txt"}
        try:
            import asyncio
            proxy = _get_proxy()

            def _sync_place():
                # Patch py-clob-client's httpx singleton to use proxy
                if proxy:
                    try:
                        import py_clob_client.http_helpers.helpers as _h
                        _h._http_client = httpx.Client(proxy=proxy, timeout=15)
                    except Exception:
                        pass

                try:
                    client = _ClobClient(
                        host=CLOB_URL,
                        key=config.POLY_PRIVATE_KEY,
                        chain_id=_POLYGON_CHAIN_ID,
                        signature_type=1 if config.POLY_PROXY_ADDRESS else 0,
                        funder=config.POLY_PROXY_ADDRESS or config.POLY_WALLET_ADDRESS,
                    )
                    # Create/derive L2 API credentials
                    try:
                        creds = client.create_api_key()
                    except Exception:
                        creds = client.derive_api_key()
                    client.set_api_creds(creds)

                    order_args = _OrderArgs(
                        token_id=token_id,
                        price=price,
                        size=size,
                        side=side.upper(),
                    )
                    signed_order = client.create_order(order_args)
                    resp = client.post_order(signed_order, _OrderType.GTC)
                    if isinstance(resp, dict):
                        # Normalize error key
                        if "errorMsg" in resp and "error" not in resp:
                            resp["error"] = resp["errorMsg"]
                        return resp
                    return {"success": True, "data": str(resp)}
                finally:
                    pass  # httpx client remains patched (proxy stays active)

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _sync_place)
        except Exception as e:
            return {"error": str(e)}
