"""
数据库配置模块
使用 SQLAlchemy ORM + SQLite
"""
import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

# 数据库文件放在 app/data/ 目录下（可通过环境变量覆盖）
DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent / "data")))
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{DATA_DIR / 'navpulse.db'}",
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 多线程需要
    echo=False,
)

# 启用 WAL 模式提升 SQLite 并发性能（多 worker 场景）
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：获取数据库 Session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库（创建所有表），并对已有数据库进行安全字段迁移"""
    from app.models import (  # noqa: F401
        User, Holding, Watchlist,
        CachedData, CachedFundValuation, CachedPortfolio,
        FundTransaction, IntradayEstimate,
        FundNavHistory, FundPortfolioCache,
        Sector,
    )
    Base.metadata.create_all(bind=engine)

    # ── 字段迁移：为旧版数据库安全添加新列（忽略已存在的列）──
    _safe_add_columns()
    print("[OK] 数据库初始化完成")


def _safe_add_columns():
    """对已有表安全地添加新列（ALTER TABLE IF NOT EXISTS 模拟）"""
    migrations = [
        # (表名, 列名, 列定义)
        ("fund_nav_history", "is_estimate", "INTEGER NOT NULL DEFAULT 0"),
        ("fund_portfolio_cache", "penetrated_from", "VARCHAR(10) DEFAULT NULL"),
    ]
    with engine.connect() as conn:
        for table, column, col_def in migrations:
            try:
                result = conn.execute(text(f"PRAGMA table_info({table})"))
                cols = [row[1] for row in result]
                if column not in cols:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"
                    ))
                    conn.commit()
                    print(f"[MIGRATE] 已添加列 {table}.{column}")
            except Exception as e:
                print(f"[MIGRATE] 跳过 {table}.{column}: {e}")
