"""
Pydantic 请求/响应模型
统一管理所有 API 的数据模型定义
"""
from pydantic import BaseModel


class HoldingRequest(BaseModel):
    """
    添加持仓请求模型 (懒人初始化模式)

    用户输入:
      - code:           基金代码
      - market_value:   当前持仓总市值 (元)
      - profit:         当前持有收益 (元，可正可负)
      - first_buy_date: 初次买入日期

    系统计算:
      - shares    = market_value / current_nav
      - unit_cost = (market_value - profit) / shares
      - total_cost = market_value - profit
    """
    code: str
    market_value: float = 0     # 当前持仓总市值
    profit: float = 0           # 当前持有收益（盈亏）
    first_buy_date: str = ""    # 初次买入日期 (YYYY-MM-DD)
    # 兼容旧字段
    amount: float = 0
    shares: float = 0
    cost: float = 0


class RegisterRequest(BaseModel):
    """注册请求模型"""
    username: str
    password: str


class WatchlistRequest(BaseModel):
    """添加自选请求模型"""
    code: str


class AddFundRequest(BaseModel):
    """添加基金请求（支持持仓或自选）"""
    code: str
    shares: float = 0
    cost: float = 0
    add_to: str = "holding"  # "holding" 或 "watchlist"


class TransactionRequest(BaseModel):
    """交易记录请求"""
    type: str        # "init" / "buy" / "sell"
    date: str        # YYYY-MM-DD
    shares: float = 0    # 份额（可选，默认用金额自动计算）
    amount: float    # 金额
    nav: float = 0   # 净值（可选）
