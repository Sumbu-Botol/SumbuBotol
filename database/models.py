from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

DATABASE_URL = config.DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


class Trade(Base):
    __tablename__ = "trades"

    id           = Column(Integer, primary_key=True, index=True)
    exchange     = Column(String, default="hyperliquid")
    pair         = Column(String, nullable=False)
    side         = Column(String, nullable=False)   # LONG / SHORT
    entry_price  = Column(Float, nullable=False)
    exit_price   = Column(Float, nullable=True)
    size_usdc    = Column(Float, nullable=False)
    leverage     = Column(Integer, nullable=False)
    pnl_usdc     = Column(Float, nullable=True)
    pnl_pct      = Column(Float, nullable=True)
    status       = Column(String, default="open")   # open / closed / stopped
    close_reason = Column(String, nullable=True)    # TP / SL / manual
    bb_width     = Column(Float, nullable=True)
    adx_value    = Column(Float, nullable=True)
    market_condition = Column(String, nullable=True)  # ranging / trending / volatile
    opened_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at    = Column(DateTime, nullable=True)


class BotState(Base):
    __tablename__ = "bot_state"

    id           = Column(Integer, primary_key=True)
    is_running   = Column(Boolean, default=False)
    daily_pnl    = Column(Float, default=0.0)
    total_pnl    = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class LearningLog(Base):
    __tablename__ = "learning_logs"

    id           = Column(Integer, primary_key=True, index=True)
    period_start = Column(DateTime, nullable=False)
    period_end   = Column(DateTime, nullable=False)
    total_trades = Column(Integer, default=0)
    win_trades   = Column(Integer, default=0)
    loss_trades  = Column(Integer, default=0)
    win_rate     = Column(Float, default=0.0)
    best_condition  = Column(String, nullable=True)
    worst_condition = Column(String, nullable=True)
    recommended_changes = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
