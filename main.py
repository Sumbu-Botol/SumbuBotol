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
from strategy.bollinger import BollingerStrategy
from risk.manager import RiskManager
from notifications.telegram import TelegramNotifier
from database.models import Trade, init_db, AsyncSessionLocal
from dashboard.app import app as dashboard_app, set_bot_runner, set_news_fetcher
from news.fetcher import NewsFetcher


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


async def daily_report_scheduler(runner: BotRunner):
    """Kirim laporan harian setiap jam 00:00 UTC."""
    while True:
        now   = datetime.now(timezone.utc)
        next_ = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_ - now).total_seconds())
        await runner.send_daily_report()


async def main():
    await init_db()

    runner = BotRunner()
    set_bot_runner(runner)

    if not runner.hl_client.is_configured():
        print("[Bot] HL_WALLET_ADDRESS / HL_PRIVATE_KEY belum di-set. "
              "Dashboard tetap berjalan, bot tidak akan trading.")
    else:
        if config.BOT_ENABLED:
            await runner.start()

    # Jalankan news fetcher (poll RSS setiap 60 detik)
    news_fetcher = NewsFetcher()
    set_news_fetcher(news_fetcher)
    asyncio.create_task(news_fetcher.start(interval=60))

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
