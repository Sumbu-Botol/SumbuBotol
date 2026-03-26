import httpx
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


class TelegramNotifier:
    def __init__(self):
        self.token   = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base    = f"https://api.telegram.org/bot{self.token}"

    async def send(self, text: str):
        if not self.token:
            print(f"[Telegram] Token tidak ada, skip: {text}")
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{self.base}/sendMessage", json={
                    "chat_id":    self.chat_id,
                    "text":       text,
                    "parse_mode": "HTML",
                })
        except Exception as e:
            print(f"[Telegram] Gagal kirim: {e}")

    # ── Template pesan ────────────────────────────────────────────────────────

    async def notify_trade_opened(self, side: str, pair: str, price: float,
                                   tp: float, sl: float, size: float):
        emoji = "🟢" if side == "LONG" else "🔴"
        await self.send(
            f"{emoji} <b>POSISI DIBUKA</b>\n"
            f"Exchange : Hyperliquid\n"
            f"Pair     : <b>{pair}/USDC</b>\n"
            f"Side     : <b>{side}</b>\n"
            f"Entry    : ${price:,.4f}\n"
            f"Size     : {size:.4f} {pair}\n"
            f"TP       : ${tp:,.4f}\n"
            f"SL       : ${sl:,.4f}\n"
            f"Waktu    : {_now()}"
        )

    async def notify_trade_closed(self, side: str, pair: str, entry: float,
                                   exit_price: float, pnl: float, reason: str):
        emoji = "✅" if pnl >= 0 else "❌"
        sign  = "+" if pnl >= 0 else ""
        await self.send(
            f"{emoji} <b>POSISI DITUTUP</b> ({reason})\n"
            f"Exchange : Hyperliquid\n"
            f"Pair     : <b>{pair}/USDC</b>\n"
            f"Side     : {side}\n"
            f"Entry    : ${entry:,.4f}\n"
            f"Exit     : ${exit_price:,.4f}\n"
            f"P&L      : <b>{sign}${pnl:.2f} USDC</b>\n"
            f"Waktu    : {_now()}"
        )

    async def notify_signal(self, action: str, pair: str, reason: str,
                             market_condition: str, adx: float):
        emoji = "📊"
        await self.send(
            f"{emoji} <b>SIGNAL: {action}</b>\n"
            f"Pair     : {pair}/USDC\n"
            f"Kondisi  : {market_condition}\n"
            f"ADX      : {adx:.1f}\n"
            f"Alasan   : {reason}\n"
            f"Waktu    : {_now()}"
        )

    async def notify_daily_report(self, balance: float, daily_pnl: float,
                                   total_trades: int, win_rate: float,
                                   open_positions: list):
        emoji_pnl = "📈" if daily_pnl >= 0 else "📉"
        sign      = "+" if daily_pnl >= 0 else ""
        pos_text  = ""
        for p in open_positions:
            pnl_emoji = "🟢" if p["unrealized_pnl"] >= 0 else "🔴"
            pos_text += (f"\n  {pnl_emoji} {p['coin']} {p['side']} "
                         f"@ ${p['entry_price']:,.2f} "
                         f"({'+' if p['unrealized_pnl']>=0 else ''}"
                         f"${p['unrealized_pnl']:.2f})")

        await self.send(
            f"📊 <b>LAPORAN HARIAN - SumbuBotol</b>\n"
            f"{'─'*30}\n"
            f"💰 Balance  : <b>${balance:,.2f} USDC</b>\n"
            f"{emoji_pnl} P&L Hari ini: <b>{sign}${daily_pnl:.2f}</b>\n"
            f"📋 Total Trade : {total_trades}\n"
            f"🎯 Win Rate    : {win_rate:.1f}%\n"
            f"{'─'*30}\n"
            f"<b>Posisi Terbuka:</b>"
            f"{pos_text if pos_text else chr(10) + '  (tidak ada)'}\n"
            f"{'─'*30}\n"
            f"⏰ {_now()}"
        )

    async def notify_risk_alert(self, message: str):
        await self.send(f"⚠️ <b>RISK ALERT</b>\n{message}\nWaktu: {_now()}")

    async def notify_bot_status(self, status: str, reason: str = ""):
        emoji = "🟢" if status == "START" else "🔴"
        await self.send(
            f"{emoji} <b>BOT {status}</b>\n"
            f"{reason}\n"
            f"Waktu: {_now()}"
        )

    async def notify_learning_report(self, report: str):
        await self.send(f"🧠 <b>WEEKLY LEARNING REPORT</b>\n\n{report}")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
