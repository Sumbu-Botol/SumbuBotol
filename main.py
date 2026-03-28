"""
SumbuBotol Trading Bot
======================
Entry point utama. Menjalankan:
  - Bot trading loop (Hyperliquid + BB Strategy)
  - Web dashboard (FastAPI)
  - Daily report scheduler
"""
import asyncio
import uvicorn
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import config
from exchanges.hyperliquid import HyperliquidClient
from exchanges.bybit import BybitClient
from exchanges.polymarket import PolymarketClient
from strategy.bollinger import BollingerStrategy
from strategy.polymarket_strategy import analyze_markets
from risk.manager import RiskManager
from notifications.telegram import TelegramNotifier
from database.models import Trade, init_db, AsyncSessionLocal
from dashboard.app import app as dashboard_app, set_bot_runner, set_bybit_bot_runner, set_news_fetcher, set_polymarket_runner
from news.fetcher import NewsFetcher

# Konversi timeframe dashboard (1m, 5m, 1h) → Bybit interval string
_TF_MAP = {"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30","1h":"60","2h":"120","4h":"240","1d":"D","1w":"W"}

def _bybit_symbol(pair: str) -> str:
    """Construct Bybit symbol. Full symbols (BTCPERP, BTCUSDT) used as-is.
    Short pairs (BTC, ETH) get USDT appended."""
    pair = pair.upper()
    if pair.endswith("PERP") or pair.endswith("USDT") or pair.endswith("USDC"):
        return pair
    return pair + "USDT"

def _bybit_settle_coin(symbol: str) -> str:
    """Return settle coin for balance check: USDC for PERP, else USDT."""
    return "USDC" if symbol.endswith("PERP") else "USDT"


class BotRunner:
    def __init__(self):
        self.hl_client  = HyperliquidClient()
        self.strategy   = BollingerStrategy()
        self.risk       = RiskManager()
        self.telegram   = TelegramNotifier()
        self.is_running = False
        self._task      = None
        # Track posisi aktif bot (pair → trade_id di DB)
        self._active_trades: dict[str, int] = {}

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        await self.telegram.notify_bot_status("START", f"Trading {config.TRADING_PAIR}/USDC | {config.TIMEFRAME}")
        self._task = asyncio.create_task(self._trading_loop())

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
        await self.telegram.notify_bot_status("STOP", "Dihentikan manual")

    async def close_all_positions(self):
        await self.telegram.notify_risk_alert("Menutup semua posisi secara manual...")
        results = await self.hl_client.close_all_positions()
        await self.telegram.notify_risk_alert(f"Semua posisi ditutup. ({len(results)} posisi)")

    # ── Trading loop ──────────────────────────────────────────────────────────

    async def _trading_loop(self):
        print(f"[Bot] Trading loop dimulai - {config.TRADING_PAIR} @ {config.TIMEFRAME}")
        while self.is_running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Bot] Error di trading loop: {e}")
                await self.telegram.notify_risk_alert(f"Error: {e}")

            await asyncio.sleep(config.POLL_INTERVAL)

    async def _tick(self):
        pair = config.TRADING_PAIR

        # 1. Ambil data candle
        candles = await self.hl_client.get_candles(pair, config.TIMEFRAME, lookback=150)
        if not candles:
            return

        # 2. Analisis strategy
        signal = self.strategy.analyze(candles)
        print(f"[Bot] Signal: {signal.action} | {signal.reason} | ADX={signal.adx:.1f}")

        # 3. Monitor posisi aktif (cek TP/SL)
        await self._monitor_open_positions(pair, signal)

        # 4. Buka trade baru kalau ada signal
        if signal.action in ("BUY", "SELL"):
            if pair not in self._active_trades:
                await self._open_trade(pair, signal)

    async def _open_trade(self, pair: str, signal):
        balance = await self.hl_client.get_balance()
        can_trade, reason = self.risk.can_open_trade(balance)
        if not can_trade:
            print(f"[Bot] Skip trade: {reason}")
            return

        is_buy  = signal.action == "BUY"
        side    = "LONG" if is_buy else "SHORT"
        price   = signal.entry_price
        size    = self.risk.calculate_position_size(balance, price)
        tp, sl  = self.risk.calculate_tp_sl(price, side)

        # Eksekusi order
        try:
            result = await self.hl_client.place_order(pair, is_buy, size, leverage=config.LEVERAGE)
            print(f"[Bot] Order placed: {side} {pair} @ ${price:.4f} size={size}")
        except Exception as e:
            print(f"[Bot] Order gagal: {e}")
            await self.telegram.notify_risk_alert(f"Order gagal: {e}")
            return

        # Simpan ke database
        async with AsyncSessionLocal() as db:
            trade = Trade(
                pair=pair, side=side, entry_price=price,
                size_usdc=config.TRADE_SIZE_USDC, leverage=config.LEVERAGE,
                status="open", bb_width=signal.bb_width,
                adx_value=signal.adx, market_condition=signal.market_condition,
            )
            db.add(trade)
            await db.commit()
            await db.refresh(trade)
            self._active_trades[pair] = trade.id

        self.risk.record_trade_opened()
        await self.telegram.notify_trade_opened(side, pair, price, tp, sl, size)

    async def _monitor_open_positions(self, pair: str, signal):
        if pair not in self._active_trades:
            return

        positions = await self.hl_client.get_open_positions()
        pos_map   = {p["coin"]: p for p in positions}

        if pair not in pos_map:
            # Posisi sudah tidak ada di exchange
            self._active_trades.pop(pair, None)
            self.risk.record_trade_closed()
            return

        pos        = pos_map[pair]
        cur_price  = float((await self.hl_client.get_all_mids()).get(pair, 0))
        if cur_price == 0:
            return

        # Ambil trade dari DB
        async with AsyncSessionLocal() as db:
            trade = await db.get(Trade, self._active_trades[pair])
            if not trade or trade.status != "open":
                return

            tp, sl = self.risk.calculate_tp_sl(trade.entry_price, trade.side)
            should_close, reason = self.risk.should_close_position(
                cur_price, trade.entry_price, tp, sl, trade.side
            )

            # Juga tutup kalau market berubah jadi volatile/trending
            if signal.market_condition != "ranging" and not should_close:
                should_close, reason = True, "market_change"

            if should_close:
                try:
                    await self.hl_client.close_position(pair)
                except Exception as e:
                    print(f"[Bot] Gagal close posisi: {e}")
                    return

                pnl = pos["unrealized_pnl"]
                if pnl < 0:
                    self.risk.record_loss(abs(pnl))

                trade.exit_price  = cur_price
                trade.pnl_usdc    = pnl
                trade.pnl_pct     = (pnl / config.TRADE_SIZE_USDC) * 100
                trade.status      = "closed"
                trade.close_reason = reason
                trade.closed_at   = datetime.now(timezone.utc)
                await db.commit()

                self._active_trades.pop(pair, None)
                self.risk.record_trade_closed()
                await self.telegram.notify_trade_closed(
                    trade.side, pair, trade.entry_price, cur_price, pnl, reason
                )

    # ── Daily report ──────────────────────────────────────────────────────────

    async def send_daily_report(self):
        balance   = await self.hl_client.get_balance()
        positions = await self.hl_client.get_open_positions()
        async with AsyncSessionLocal() as db:
            stats = await _calc_stats(db)
        await self.telegram.notify_daily_report(
            balance, stats["daily_pnl"], stats["total_trades"],
            stats["win_rate"], positions
        )


class BybitBotRunner:
    """Bot trading loop untuk Bybit Perpetual Futures."""

    def __init__(self):
        self.bybit      = BybitClient()
        self.strategy   = BollingerStrategy(config.BYBIT_BOT_PERSONA)
        self.risk       = RiskManager()
        self.telegram   = TelegramNotifier()
        self.is_running = False
        self._task      = None
        self._active_trades: dict[str, int] = {}   # symbol → trade DB id

    def is_configured(self) -> bool:
        return bool(config.BYBIT_API_KEY and config.BYBIT_API_SECRET)

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.strategy.set_persona(config.BYBIT_BOT_PERSONA)
        pair   = _bybit_symbol(config.BYBIT_BOT_PAIR)
        tf     = config.BYBIT_BOT_TIMEFRAME
        lev    = config.BYBIT_BOT_LEVERAGE
        size   = config.BYBIT_BOT_SIZE
        await self.telegram.notify_bot_status("START", f"[Bybit] {pair} | {tf} | x{lev} | ${size}/trade")
        self._task = asyncio.create_task(self._trading_loop())

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
        await self.telegram.notify_bot_status("STOP", "[Bybit] Dihentikan manual")

    async def close_all_positions(self):
        await self.telegram.notify_risk_alert("[Bybit] Menutup semua posisi...")
        results = await self.bybit.close_all_positions()
        await self.telegram.notify_risk_alert(f"[Bybit] {len(results)} posisi ditutup.")

    # ── Trading loop ──────────────────────────────────────────────────────────

    async def _trading_loop(self):
        symbol = _bybit_symbol(config.BYBIT_BOT_PAIR)
        print(f"[BybitBot] Loop dimulai — {symbol} @ {config.BYBIT_BOT_TIMEFRAME}")
        while self.is_running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[BybitBot] Error: {e}")
                await self.telegram.notify_risk_alert(f"[Bybit] Error: {e}")
            await asyncio.sleep(config.POLL_INTERVAL)

    async def _tick(self):
        symbol   = _bybit_symbol(config.BYBIT_BOT_PAIR)
        interval = _TF_MAP.get(config.BYBIT_BOT_TIMEFRAME, "60")

        # 1. Ambil candle
        raw = await self.bybit.get_candles(symbol, interval, limit=200)
        if not raw:
            return

        # Bybit returns newest first: [timestamp, open, high, low, close, volume, ...]
        candles = [
            {"time": int(c[0]), "open": float(c[1]), "high": float(c[2]),
             "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
            for c in reversed(raw)
        ]

        # 2. Analisis
        signal = self.strategy.analyze(candles)
        print(f"[BybitBot] Signal: {signal.action} | {signal.reason[:60]}")

        # 3. Monitor posisi aktif (deteksi kalau sudah ditutup TP/SL)
        await self._monitor_positions(symbol, signal)

        # 4. Buka trade baru
        if signal.action in ("BUY", "SELL") and symbol not in self._active_trades:
            await self._open_trade(symbol, signal)

    async def _open_trade(self, symbol: str, signal):
        try:
            bal        = await self.bybit.get_balance()
            settle     = _bybit_settle_coin(symbol)
            avail_bal  = bal.get(settle, 0.0)
        except Exception as e:
            print(f"[BybitBot] balance error: {e}")
            return

        can_trade, reason = self.risk.can_open_trade(avail_bal)
        if not can_trade:
            print(f"[BybitBot] Skip: {reason}")
            return

        side     = "Buy" if signal.action == "BUY" else "Sell"
        db_side  = "LONG" if side == "Buy" else "SHORT"
        price    = signal.entry_price
        leverage = config.BYBIT_BOT_LEVERAGE
        size_usd = config.BYBIT_BOT_SIZE

        # Leverage set dulu
        try:
            await self.bybit.set_leverage(symbol, leverage)
        except Exception:
            pass

        # TP/SL dari persona (atau override dari settings)
        persona = self.strategy.persona
        tp_pct  = config.BYBIT_BOT_TP or persona["tp_pct"]
        sl_pct  = config.BYBIT_BOT_SL or persona["sl_pct"]
        if side == "Buy":
            tp_price = round(price * (1 + tp_pct / 100), 2)
            sl_price = round(price * (1 - sl_pct / 100), 2)
        else:
            tp_price = round(price * (1 - tp_pct / 100), 2)
            sl_price = round(price * (1 + sl_pct / 100), 2)

        # Qty = modal × leverage / harga
        qty = round(size_usd * leverage / price, 3)

        try:
            result = await self.bybit.place_order(symbol, side, qty, tp=tp_price, sl=sl_price)
            if result.get("retCode") != 0:
                raise RuntimeError(result.get("retMsg"))
            print(f"[BybitBot] Order OK: {side} {symbol} qty={qty} TP={tp_price} SL={sl_price}")
        except Exception as e:
            print(f"[BybitBot] Order gagal: {e}")
            await self.telegram.notify_risk_alert(f"[Bybit] Order gagal: {e}")
            return

        async with AsyncSessionLocal() as db:
            trade = Trade(
                pair=symbol, side=db_side, entry_price=price,
                size_usdc=size_usd, leverage=leverage, status="open",
                bb_width=signal.bb_width, adx_value=signal.adx,
                market_condition=signal.market_condition,
            )
            db.add(trade)
            await db.commit()
            await db.refresh(trade)
            self._active_trades[symbol] = trade.id

        self.risk.record_trade_opened()
        await self.telegram.notify_trade_opened(db_side, symbol, price, tp_price, sl_price, qty)

    async def _monitor_positions(self, symbol: str, signal):
        if symbol not in self._active_trades:
            return

        try:
            positions = await self.bybit.get_positions()
        except Exception:
            return

        pos_map = {p["symbol"]: p for p in positions}

        if symbol not in pos_map:
            # Posisi sudah ditutup oleh Bybit (TP/SL hit atau manual)
            trade_id = self._active_trades.pop(symbol, None)
            self.risk.record_trade_closed()
            if trade_id:
                async with AsyncSessionLocal() as db:
                    trade = await db.get(Trade, trade_id)
                    if trade and trade.status == "open":
                        trade.status      = "closed"
                        trade.close_reason = "bybit_closed"
                        trade.closed_at   = datetime.now(timezone.utc)
                        await db.commit()
            return

        # Posisi masih ada — cek apakah market berubah trending/volatile
        pos = pos_map[symbol]
        if signal.market_condition != "ranging":
            try:
                await self.bybit.close_position(symbol, pos["side"], pos["size"])
                print(f"[BybitBot] Posisi ditutup karena market {signal.market_condition}")
            except Exception as e:
                print(f"[BybitBot] close error: {e}")
                return

            pnl      = pos["unrealized_pnl"]
            cur_price = pos["mark_price"]
            trade_id  = self._active_trades.pop(symbol, None)
            self.risk.record_trade_closed()
            if pnl < 0:
                self.risk.record_loss(abs(pnl))
            if trade_id:
                async with AsyncSessionLocal() as db:
                    trade = await db.get(Trade, trade_id)
                    if trade and trade.status == "open":
                        trade.exit_price   = cur_price
                        trade.pnl_usdc     = pnl
                        trade.pnl_pct      = (pnl / trade.size_usdc * 100) if trade.size_usdc else 0
                        trade.status       = "closed"
                        trade.close_reason = f"market_{signal.market_condition}"
                        trade.closed_at    = datetime.now(timezone.utc)
                        await db.commit()
            await self.telegram.notify_trade_closed(
                pos["side"], symbol, pos["entry_price"], cur_price, pnl,
                f"market_{signal.market_condition}"
            )


async def _calc_stats(db: AsyncSession) -> dict:
    from sqlalchemy import func
    today = datetime.now(timezone.utc).date()

    total = (await db.execute(
        select(func.count(Trade.id)).where(Trade.status == "closed")
    )).scalar() or 0

    wins = (await db.execute(
        select(func.count(Trade.id)).where(Trade.status == "closed", Trade.pnl_usdc > 0)
    )).scalar() or 0

    daily_pnl = (await db.execute(
        select(func.sum(Trade.pnl_usdc)).where(
            Trade.status == "closed",
            Trade.closed_at >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        )
    )).scalar() or 0.0

    return {
        "total_trades": total,
        "win_rate":     round((wins / total * 100) if total > 0 else 0, 1),
        "daily_pnl":    round(float(daily_pnl), 2),
    }


class PolymarketBotRunner:
    """Bot otomatis Polymarket: scan market → deteksi mispricing → eksekusi bet."""

    def __init__(self):
        self.client     = PolymarketClient()
        self.telegram   = TelegramNotifier()
        self.is_running = False
        self._task      = None
        self.scan_interval = int(config.POLY_BOT_SCAN_INTERVAL)
        self.max_bet    = float(config.POLY_BOT_SIZE)
        self.min_bet    = 1.0
        self.executed_markets: set = set()   # hindari bet market yang sama

    def is_configured(self) -> bool:
        return self.client.is_configured()

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._loop())
        print(f"[PolyBot] Started — scan setiap {self.scan_interval}s, max bet ${self.max_bet}")

    async def stop(self):
        self.is_running = False
        if self._task:
            self._task.cancel()
        print("[PolyBot] Stopped")

    def status(self) -> dict:
        return {
            "is_running":    self.is_running,
            "scan_interval": self.scan_interval,
            "max_bet_usdc":  self.max_bet,
            "configured":    self.is_configured(),
        }

    async def _loop(self):
        while self.is_running:
            try:
                await self._scan_and_execute()
            except Exception as e:
                print(f"[PolyBot] Loop error: {e}")
            await asyncio.sleep(self.scan_interval)

    async def _scan_and_execute(self):
        markets = await self.client.get_popular_markets(limit=30)
        if not markets:
            print("[PolyBot] Tidak ada market data")
            return

        opps = analyze_markets(markets, min_bet=self.min_bet, max_bet=self.max_bet)
        if not opps:
            print(f"[PolyBot] Tidak ada peluang ditemukan dari {len(markets)} market")
            return

        print(f"[PolyBot] {len(opps)} peluang ditemukan, eksekusi top 3")
        for opp in opps[:3]:
            cid = opp["condition_id"]
            if cid in self.executed_markets:
                continue

            print(f"[PolyBot] {opp['strategy'].upper()} | {opp['market'][:50]} | "
                  f"+{opp['expected_profit_pct']}% | {opp['action']}")

            success = await self._execute(opp)
            if success:
                self.executed_markets.add(cid)
                await self.telegram.notify_risk_alert(
                    f"[Polymarket] {opp['strategy'].upper()} bet\n"
                    f"Market: {opp['market'][:60]}\n"
                    f"Action: {opp['action']}\n"
                    f"Expected profit: +{opp['expected_profit_pct']}%\n"
                    f"Reason: {opp['reason']}"
                )

    async def _execute(self, opp: dict) -> bool:
        try:
            action = opp["action"]
            if action in ("BUY_YES", "BUY_BOTH"):
                size  = opp["bet_yes_usdc"]
                price = opp["yes_price"]
                r = await self.client.place_order(opp["yes_token_id"], "buy", price, size)
                if r.get("error"):
                    print(f"[PolyBot] YES order error: {r['error']}")
                    return False
                print(f"[PolyBot] YES order OK: size=${size} @ {price*100:.1f}%")

            if action in ("BUY_NO", "BUY_BOTH"):
                size  = opp["bet_no_usdc"]
                price = opp["no_price"]
                r = await self.client.place_order(opp["no_token_id"], "buy", price, size)
                if r.get("error"):
                    print(f"[PolyBot] NO order error: {r['error']}")
                    return False
                print(f"[PolyBot] NO order OK: size=${size} @ {price*100:.1f}%")

            return True
        except Exception as e:
            print(f"[PolyBot] Execute error: {e}")
            return False


async def daily_report_scheduler(runner: BotRunner):
    """Kirim laporan harian setiap jam 00:00 UTC."""
    while True:
        now   = datetime.now(timezone.utc)
        next_ = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_ - now).total_seconds())
        await runner.send_daily_report()


async def main():
    await init_db()

    # ── Hyperliquid bot ───────────────────────────────────────────────────────
    runner = BotRunner()
    set_bot_runner(runner)

    if not runner.hl_client.is_configured():
        print("[Bot] HL_WALLET_ADDRESS / HL_PRIVATE_KEY belum di-set. "
              "Dashboard tetap berjalan, bot HL tidak akan trading.")
    else:
        if config.BOT_ENABLED:
            await runner.start()

    # ── Bybit bot ─────────────────────────────────────────────────────────────
    bybit_runner = BybitBotRunner()
    set_bybit_bot_runner(bybit_runner)

    if not bybit_runner.is_configured():
        print("[BybitBot] BYBIT_API_KEY / BYBIT_API_SECRET belum di-set. Bot Bybit tidak aktif.")
    else:
        if config.BOT_ENABLED:
            await bybit_runner.start()

    # ── Polymarket bot ───────────────────────────────────────────────────────
    poly_runner = PolymarketBotRunner()
    set_polymarket_runner(poly_runner)
    if poly_runner.is_configured():
        if config.BOT_ENABLED:
            await poly_runner.start()
    else:
        print("[PolyBot] POLY_WALLET_ADDRESS belum diset. Bot Polymarket tidak aktif.")

    # Jalankan news fetcher (poll RSS setiap 60 detik)
    news_fetcher = NewsFetcher()
    set_news_fetcher(news_fetcher)
    asyncio.create_task(news_fetcher.start(interval=30))

    # Jalankan daily report scheduler
    asyncio.create_task(daily_report_scheduler(runner))

    # Jalankan FastAPI dashboard
    server_config = uvicorn.Config(
        dashboard_app,
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(server_config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
