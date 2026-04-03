import asyncio
import httpx
import json
import time
import eth_account
from eth_account.signers.local import LocalAccount
from datetime import datetime, timezone
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

BASE_URL_MAINNET = "https://api.hyperliquid.xyz"
BASE_URL_TESTNET = "https://api.hyperliquid-testnet.xyz"


class HyperliquidClient:
    def __init__(self):
        self.base_url = BASE_URL_TESTNET if config.HL_TESTNET else BASE_URL_MAINNET
        self.wallet_address = config.HL_WALLET_ADDRESS
        self.account: Optional[LocalAccount] = None
        if config.HL_PRIVATE_KEY:
            self.account = eth_account.Account.from_key(config.HL_PRIVATE_KEY)

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _post_info(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{self.base_url}/info", json=payload)
            r.raise_for_status()
            return r.json()

    async def _post_exchange(self, action: dict, vault_address: Optional[str] = None) -> dict:
        if not self.account:
            raise RuntimeError("Private key tidak di-set. Tambahkan HL_PRIVATE_KEY ke env var.")

        nonce = int(time.time() * 1000)
        connection_id = self._build_connection_id(action, nonce, vault_address)
        signature = self.account.sign_message(
            eth_account.messages.encode_defunct(hexstr=connection_id)
        )

        payload = {
            "action": action,
            "nonce": nonce,
            "signature": {"r": hex(signature.r), "s": hex(signature.s), "v": signature.v},
        }
        if vault_address:
            payload["vaultAddress"] = vault_address

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{self.base_url}/exchange", json=payload)
            r.raise_for_status()
            return r.json()

    def _build_connection_id(self, action: dict, nonce: int, vault_address: Optional[str]) -> str:
        import hashlib
        data = json.dumps({"action": action, "nonce": nonce, "vaultAddress": vault_address}, sort_keys=True)
        return "0x" + hashlib.sha256(data.encode()).hexdigest()

    # ── Market data ───────────────────────────────────────────────────────────

    async def get_all_mids(self) -> dict:
        """Ambil harga mid semua aset."""
        return await self._post_info({"type": "allMids"})

    async def get_candles(self, coin: str, interval: str = "1h", lookback: int = 100) -> list:
        """Ambil data OHLCV. interval: 1m, 5m, 15m, 1h, 4h, 1d"""
        end_time   = int(time.time() * 1000)
        start_time = end_time - (lookback * _interval_ms(interval))
        data = await self._post_info({
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": start_time, "endTime": end_time}
        })
        candles = []
        for c in data:
            candles.append({
                "time":   datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc),
                "open":   float(c["o"]),
                "high":   float(c["h"]),
                "low":    float(c["l"]),
                "close":  float(c["c"]),
                "volume": float(c["v"]),
            })
        return candles

    async def get_orderbook(self, coin: str) -> dict:
        return await self._post_info({"type": "l2Book", "coin": coin})

    # ── Account data ─────────────────────────────────────────────────────────

    async def get_account_state(self) -> dict:
        """Ambil balance, posisi, margin."""
        return await self._post_info({
            "type": "clearinghouseState",
            "user": self.wallet_address
        })

    async def get_balance(self) -> float:
        """Saldo USDC tersedia."""
        state = await self.get_account_state()
        return float(state.get("crossMarginSummary", {}).get("accountValue", 0))

    async def get_open_positions(self) -> list:
        """Daftar posisi terbuka."""
        state = await self.get_account_state()
        positions = []
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            size = float(pos.get("szi", 0))
            if size != 0:
                positions.append({
                    "coin":         pos.get("coin"),
                    "side":         "LONG" if size > 0 else "SHORT",
                    "size":         abs(size),
                    "entry_price":  float(pos.get("entryPx", 0)),
                    "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                    "leverage":     pos.get("leverage", {}).get("value", 1),
                })
        return positions

    async def get_trade_history(self, lookback_days: int = 30) -> list:
        """History trade terakhir."""
        start_time = int((time.time() - lookback_days * 86400) * 1000)
        return await self._post_info({
            "type": "userFills",
            "user": self.wallet_address,
            "startTime": start_time,
        })

    # ── Order execution ───────────────────────────────────────────────────────

    async def place_order(
        self,
        coin: str,
        is_buy: bool,
        size: float,
        price: Optional[float] = None,
        leverage: int = 5,
        reduce_only: bool = False,
    ) -> dict:
        """Buka order market atau limit."""
        await self._set_leverage(coin, leverage)

        order_type = {"limit": {"tif": "Ioc"}} if price is None else {"limit": {"tif": "Gtc"}}
        px = price if price else await self._get_market_price(coin, is_buy)

        action = {
            "type": "order",
            "orders": [{
                "a": await self._coin_to_asset_id(coin),
                "b": is_buy,
                "p": str(round(px, 6)),
                "s": str(round(size, 6)),
                "r": reduce_only,
                "t": order_type,
            }],
            "grouping": "na",
        }
        return await self._post_exchange(action)

    async def close_position(self, coin: str) -> dict:
        """Tutup semua posisi untuk coin tertentu."""
        positions = await self.get_open_positions()
        for pos in positions:
            if pos["coin"] == coin:
                is_buy = pos["side"] == "SHORT"
                return await self.place_order(coin, is_buy, pos["size"], reduce_only=True)
        return {"status": "no_position"}

    async def close_all_positions(self) -> list:
        """Tutup semua posisi terbuka."""
        positions = await self.get_open_positions()
        results = []
        for pos in positions:
            result = await self.close_position(pos["coin"])
            results.append(result)
        return results

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _set_leverage(self, coin: str, leverage: int):
        action = {
            "type": "updateLeverage",
            "asset": await self._coin_to_asset_id(coin),
            "isCross": True,
            "leverage": leverage,
        }
        await self._post_exchange(action)

    async def _get_market_price(self, coin: str, is_buy: bool) -> float:
        mids = await self.get_all_mids()
        return float(mids.get(coin, 0))

    async def _coin_to_asset_id(self, coin: str) -> int:
        meta = await self._post_info({"type": "meta"})
        for i, asset in enumerate(meta.get("universe", [])):
            if asset["name"] == coin:
                return i
        raise ValueError(f"Coin {coin} tidak ditemukan di Hyperliquid")

    def is_configured(self) -> bool:
        return bool(self.wallet_address and config.HL_PRIVATE_KEY)


def _interval_ms(interval: str) -> int:
    mapping = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
               "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
    return mapping.get(interval, 3_600_000)
