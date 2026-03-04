"""
ORM 数据模型
"""
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=False)

    # 关联持仓
    holdings = relationship("Holding", back_populates="owner", cascade="all, delete-orphan")
    # 关联自选
    watchlist = relationship("Watchlist", back_populates="owner", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}')>"


class Holding(Base):
    """持仓表"""
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    code = Column(String(10), nullable=False)       # 基金代码
    shares = Column(Float, nullable=False)            # 持有份额
    cost_price = Column(Float, nullable=False)        # 总投入本金（元）

    # 关联用户
    owner = relationship("User", back_populates="holdings")

    def __repr__(self):
        return f"<Holding(id={self.id}, code='{self.code}', shares={self.shares})>"

    def to_dict(self):
        return {
            "code": self.code,
            "shares": self.shares,
            "cost": self.cost_price,
        }


class Watchlist(Base):
    """自选基金表"""
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    fund_code = Column(String(10), nullable=False)  # 基金代码

    # 确保每个用户对同一基金只有一条记录
    __table_args__ = (
        UniqueConstraint('user_id', 'fund_code', name='uix_user_fund'),
    )

    # 关联用户
    owner = relationship("User", back_populates="watchlist")

    def __repr__(self):
        return f"<Watchlist(id={self.id}, user_id={self.user_id}, fund_code='{self.fund_code}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "fund_code": self.fund_code,
        }


# ══════════════════════════════════════════════════════════
#  持久化缓存表 — 服务器重启后自动恢复上次数据
# ══════════════════════════════════════════════════════════

class CachedData(Base):
    """
    通用 KV 持久化缓存表
    key 为数据类型标识（如 "market_indices", "stock_distribution", "sectors"）
    value 为 JSON 字符串
    """
    __tablename__ = "cached_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False, default="{}")
    updated_at = Column(String(30), nullable=False, default="")

    def __repr__(self):
        return f"<CachedData(key='{self.key}', updated_at='{self.updated_at}')>"


class CachedFundValuation(Base):
    """
    基金估值持久化缓存
    每只基金一条记录，更新时覆盖
    """
    __tablename__ = "cached_fund_valuations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_code = Column(String(10), unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False, default="{}")  # JSON
    updated_at = Column(String(30), nullable=False, default="")

    def __repr__(self):
        return f"<CachedFundValuation(fund_code='{self.fund_code}', updated_at='{self.updated_at}')>"


class CachedPortfolio(Base):
    """
    用户持仓估值持久化缓存
    """
    __tablename__ = "cached_portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, unique=True, nullable=False, index=True)
    data = Column(Text, nullable=False, default="{}")  # JSON
    updated_at = Column(String(30), nullable=False, default="")

    def __repr__(self):
        return f"<CachedPortfolio(user_id={self.user_id}, updated_at='{self.updated_at}')>"


class FundTransaction(Base):
    """基金交易记录（初始化/买入/卖出）"""
    __tablename__ = "fund_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    fund_code = Column(String(10), nullable=False, index=True)
    type = Column(String(10), nullable=False)   # "init" / "buy" / "sell"
    date = Column(String(10), nullable=False)   # YYYY-MM-DD
    shares = Column(Float, nullable=False)       # 份额
    amount = Column(Float, nullable=False)       # 交易金额（元）— init时为市值
    nav = Column(Float, nullable=True)           # 交易时净值
    created_at = Column(String(30), nullable=False, default="")

    __table_args__ = (
        Index('ix_tx_user_fund', 'user_id', 'fund_code'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "fund_code": self.fund_code,
            "type": self.type,
            "date": self.date,
            "shares": round(self.shares, 4),
            "amount": round(self.amount, 2),
            "nav": round(self.nav, 4) if self.nav else None,
            "created_at": self.created_at,
        }


class IntradayEstimate(Base):
    """基金日内估值快照（实时走势图数据源）"""
    __tablename__ = "intraday_estimates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_code = Column(String(10), nullable=False, index=True)
    trade_date = Column(String(10), nullable=False, index=True)
    time = Column(String(8), nullable=False)
    estimate_change = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint('fund_code', 'trade_date', 'time', name='uix_intraday'),
        Index('ix_intraday_code_date', 'fund_code', 'trade_date'),
    )


class FundNavHistory(Base):
    """
    基金历史净值持久化表
    每只基金的每个净值日期存一行，支持增量更新、缺失数据自动补全

    is_estimate 含义：
      0 = 官方净值（akshare 历史净值，已确认）
      1 = 临时估算净值（收盘后基于最后实时估值折算，等待官方发布后自动覆盖）
    """
    __tablename__ = "fund_nav_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_code = Column(String(10), nullable=False, index=True)
    date = Column(String(10), nullable=False)          # YYYY-MM-DD
    nav = Column(Float, nullable=False)                # 单位净值
    change_pct = Column(Float, nullable=True)          # 日涨跌幅 %（可为null，后台补全）
    is_filled = Column(Integer, nullable=False, default=1)  # 1=正常数据, 0=待补全占位符
    is_estimate = Column(Integer, nullable=False, default=0)  # 0=官方净值, 1=临时估算

    __table_args__ = (
        UniqueConstraint('fund_code', 'date', name='uix_nav_history'),
        Index('ix_nav_history_code_date', 'fund_code', 'date'),
    )


class Sector(Base):
    """
    板块数据表（手动维护，不爬取）
    由管理员通过 POST /api/market/sectors 写入

    每个板块对应若干只基金，涨跌幅由调度器根据基金实时估值自动计算
    """
    __tablename__ = "sectors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, index=True)  # 板块名称（唯一键）
    fund_codes = Column(Text, nullable=False, default="[]")             # JSON 数组，该板块包含的基金代码
    streak = Column(Integer, nullable=False, default=0)                  # 连涨/连跌天数（正=连涨，负=连跌）
    sort_order = Column(Integer, nullable=False, default=0)              # 排序权重（越大越靠前）
    updated_at = Column(String(30), nullable=False, default="")         # 最后更新时间

    def to_dict(self, change_pct: float = 0.0) -> dict:
        import json
        return {
            "name": self.name,
            "fund_codes": json.loads(self.fund_codes or "[]"),
            "fund_count": len(json.loads(self.fund_codes or "[]")),
            "change_pct": round(change_pct, 2),
            "streak": self.streak,
            "sort_order": self.sort_order,
            "updated_at": self.updated_at,
        }

    def __repr__(self):
        return f"<Sector(name='{self.name}')>"


class FundPortfolioCache(Base):
    """
    基金重仓持仓持久化缓存
    每只基金一行，保存最新一期季度持仓 JSON
    """
    __tablename__ = "fund_portfolio_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_code = Column(String(10), unique=True, nullable=False, index=True)
    holdings_json = Column(Text, nullable=False, default="[]")  # JSON array
    data_date = Column(String(10), nullable=True)       # 数据对应的季度末日期
    updated_at = Column(String(30), nullable=False, default="")  # 最后爬取时间
    penetrated_from = Column(String(10), nullable=True, default=None)  # 联接基金穿透的底层 ETF 代码

    def __repr__(self):
        return f"<FundPortfolioCache(fund_code='{self.fund_code}', data_date='{self.data_date}')>"
