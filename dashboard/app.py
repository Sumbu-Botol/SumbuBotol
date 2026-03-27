from fastapi import FastAPI, Request, Depends, HTTPException, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime, timezone, timedelta
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from database.models import Trade, BotState, LearningLog, get_db, init_db
from strategy.personas import list_personas, get_persona
from news.fetcher import NewsFetcher
import json

app = FastAPI(title="SumbuBotol Trading Dashboard")

BASE_DIR   = os.path.dirname(__file__)
templates  = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
serializer = URLSafeTimedSerializer(config.DASHBOARD_PASSWORD)

# Global references (diset dari main.py)
_bot_runner   = None
_news_fetcher: NewsFetcher = None
_ws_clients: list[WebSocket] = []

def set_bot_runner(runner):
    global _bot_runner
    _bot_runner = runner

def set_news_fetcher(fetcher: NewsFetcher):
    global _news_fetcher
    _news_fetcher = fetcher
    # Broadcast artikel baru ke semua WS client
    async def broadcast(article: dict):
        dead = []
        for ws in _ws_clients:
            try:
                await ws.send_json({"type": "news", "data": article})
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_clients.remove(ws)
    fetcher.on_new_article(broadcast)


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────

def check_auth(request: Request) -> bool:
    token = request.cookies.get("auth_token")
    if not token:
        return False
    try:
        serializer.loads(token, max_age=86400)
        return True
    except Exception:
        return False


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == config.DASHBOARD_PASSWORD:
        token    = serializer.dumps("authenticated")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("auth_token", token, httponly=True, max_age=86400)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Password salah"})


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login")
    response.delete_cookie("auth_token")
    return response


# ── Dashboard pages ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    if not check_auth(request):
        return RedirectResponse("/login")

    # Ambil data
    balance        = await _get_balance()
    open_positions = await _get_open_positions()
    recent_trades  = await _get_recent_trades(db, limit=10)
    stats          = await _get_stats(db)
    bot_running    = _bot_runner.is_running if _bot_runner else False

    return templates.TemplateResponse("dashboard.html", {
        "request":         request,
        "balance":         balance,
        "open_positions":  open_positions,
        "recent_trades":   recent_trades,
        "stats":           stats,
        "bot_running":     bot_running,
        "active_persona":  get_persona(config.ACTIVE_PERSONA),
        "active_exchange": config.ACTIVE_EXCHANGE,
        "config":          config,
        "now":             datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
    })


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not check_auth(request):
        return RedirectResponse("/login")
    trades = await _get_recent_trades(db, limit=100)
    return templates.TemplateResponse("history.html", {"request": request, "trades": trades})


@app.get("/personas", response_class=HTMLResponse)
async def personas_page(request: Request):
    if not check_auth(request):
        return RedirectResponse("/login")
    personas       = list_personas()
    active_persona = get_persona(config.ACTIVE_PERSONA)
    persona_names  = {p["id"]: p["name"] for p in personas}
    return templates.TemplateResponse("personas.html", {
        "request":          request,
        "personas":         personas,
        "active_persona":   active_persona,
        "persona_names_json": json.dumps(persona_names),
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not check_auth(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse("settings.html", {"request": request, "config": config})


# ── API endpoints (untuk dashboard realtime) ─────────────────────────────────

@app.get("/api/status")
async def api_status():
    try:
        balance        = await _get_balance()
        open_positions = await _get_open_positions()
    except Exception:
        balance        = 0.0
        open_positions = []
    bot_running = _bot_runner.is_running if _bot_runner else False
    return {
        "bot_running":    bot_running,
        "balance":        balance,
        "open_positions": open_positions,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/persona/switch")
async def persona_switch(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    data       = await request.json()
    persona_id = data.get("persona_id")
    persona    = get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=400, detail="Persona tidak ditemukan")

    # Update config runtime
    config.ACTIVE_PERSONA = persona_id
    # Update timeframe dari persona
    config.TIMEFRAME = persona["timeframe"]

    # Restart bot dengan persona baru
    if _bot_runner:
        was_running = _bot_runner.is_running
        await _bot_runner.stop()
        _bot_runner.strategy.set_persona(persona_id)
        if was_running:
            await _bot_runner.start()

    return {"status": "switched", "persona": persona["name"]}


@app.post("/api/bot/start")
async def bot_start(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    if _bot_runner:
        await _bot_runner.start()
    return {"status": "started"}


@app.post("/api/bot/stop")
async def bot_stop(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    if _bot_runner:
        await _bot_runner.stop()
    return {"status": "stopped"}


@app.post("/api/bot/close-all")
async def bot_close_all(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    if _bot_runner:
        await _bot_runner.close_all_positions()
    return {"status": "closing_all"}


@app.post("/api/settings")
async def update_settings(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    data = await request.json()
    # Update config runtime (tidak persisten, perlu restart untuk permanent)
    allowed = ["TRADING_PAIR", "LEVERAGE", "TAKE_PROFIT_PCT", "STOP_LOSS_PCT",
               "TRADE_SIZE_USDC", "BB_PERIOD", "BB_STD", "ADX_THRESHOLD"]
    for key, val in data.items():
        if key in allowed and hasattr(config, key):
            setattr(config, key, type(getattr(config, key))(val))
    return {"status": "updated"}


@app.get("/api/pnl-chart")
async def pnl_chart(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Trade.closed_at, Trade.pnl_usdc)
        .where(Trade.status == "closed")
        .order_by(Trade.closed_at)
        .limit(100)
    )
    rows = result.fetchall()
    cumulative, total = [], 0.0
    for row in rows:
        total += float(row.pnl_usdc or 0)
        cumulative.append({
            "time": row.closed_at.isoformat() if row.closed_at else None,
            "pnl":  round(total, 2),
        })
    return cumulative


# ── Bybit API routes ─────────────────────────────────────────────────────────

def _bybit():
    from exchanges.bybit import BybitClient
    return BybitClient()

@app.get("/api/bybit/balance")
async def bybit_balance(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    return await _bybit().get_balance()

@app.get("/api/bybit/positions")
async def bybit_positions(request: Request, settle: str = "ALL"):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    return await _bybit().get_positions(settle)

@app.post("/api/bybit/close")
async def bybit_close(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    d = await request.json()
    return await _bybit().close_position(d["symbol"], d["side"], float(d["size"]))

@app.post("/api/bybit/close-all")
async def bybit_close_all(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    return await _bybit().close_all_positions()

@app.post("/api/bybit/tp-sl")
async def bybit_tp_sl(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    d = await request.json()
    return await _bybit().set_tp_sl(
        d["symbol"],
        tp=float(d.get("tp", 0)) or None,
        sl=float(d.get("sl", 0)) or None,
    )

@app.post("/api/bybit/order")
async def bybit_order(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    d = await request.json()
    return await _bybit().place_order(
        symbol=d["symbol"], side=d["side"], qty=float(d["qty"]),
        order_type=d.get("type", "Market"),
        price=float(d["price"]) if d.get("price") else None,
        tp=float(d["tp"]) if d.get("tp") else None,
        sl=float(d["sl"]) if d.get("sl") else None,
    )

@app.post("/api/exchange/switch")
async def exchange_switch(request: Request):
    if not check_auth(request):
        raise HTTPException(status_code=401)
    d = await request.json()
    ex = d.get("exchange", "bybit")
    if ex not in ("bybit", "hyperliquid"):
        raise HTTPException(status_code=400, detail="Invalid exchange")
    config.ACTIVE_EXCHANGE = ex
    return {"active_exchange": ex}

# ── News routes ──────────────────────────────────────────────────────────────

@app.get("/news", response_class=HTMLResponse)
async def news_page(request: Request):
    if not check_auth(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse("news.html", {"request": request})


@app.get("/api/news/crypto")
async def api_news_crypto(limit: int = 50):
    if not _news_fetcher:
        return []
    return _news_fetcher.get_crypto(limit)


@app.get("/api/news/global")
async def api_news_global(limit: int = 50):
    if not _news_fetcher:
        return []
    return _news_fetcher.get_global(limit)


@app.get("/api/news/latest")
async def api_news_latest(limit: int = 20):
    if not _news_fetcher:
        return []
    return _news_fetcher.get_latest(limit)


@app.websocket("/ws/news")
async def ws_news(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        # Kirim SEMUA artikel crypto + global secara terpisah saat pertama connect
        if _news_fetcher:
            await websocket.send_json({
                "type": "init",
                "crypto": _news_fetcher.get_crypto(100),
                "global": _news_fetcher.get_global(100),
            })
        while True:
            await websocket.receive_text()   # keep alive
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_balance() -> float:
    try:
        if _bot_runner and _bot_runner.hl_client:
            return await _bot_runner.hl_client.get_balance()
    except Exception:
        pass
    return 0.0


async def _get_open_positions() -> list:
    try:
        if _bot_runner and _bot_runner.hl_client:
            return await _bot_runner.hl_client.get_open_positions()
    except Exception:
        pass
    return []


async def _get_recent_trades(db: AsyncSession, limit: int = 10) -> list:
    result = await db.execute(
        select(Trade).order_by(desc(Trade.opened_at)).limit(limit)
    )
    return result.scalars().all()


async def _get_stats(db: AsyncSession) -> dict:
    total_result = await db.execute(select(func.count(Trade.id)).where(Trade.status == "closed"))
    total = total_result.scalar() or 0

    win_result = await db.execute(
        select(func.count(Trade.id))
        .where(Trade.status == "closed", Trade.pnl_usdc > 0)
    )
    wins = win_result.scalar() or 0

    pnl_result = await db.execute(
        select(func.sum(Trade.pnl_usdc)).where(Trade.status == "closed")
    )
    total_pnl = pnl_result.scalar() or 0.0

    today = datetime.now(timezone.utc).date()
    daily_result = await db.execute(
        select(func.sum(Trade.pnl_usdc))
        .where(Trade.status == "closed",
               Trade.closed_at >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
    )
    daily_pnl = daily_result.scalar() or 0.0

    return {
        "total_trades": total,
        "win_trades":   wins,
        "loss_trades":  total - wins,
        "win_rate":     round((wins / total * 100) if total > 0 else 0, 1),
        "total_pnl":    round(float(total_pnl), 2),
        "daily_pnl":    round(float(daily_pnl), 2),
    }
