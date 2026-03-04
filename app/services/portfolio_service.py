"""
持仓管理服务
负责持仓数据的增删改查（使用 SQLite / SQLAlchemy ORM）
数据模型: {"code": "005963", "shares": 1000.0, "cost": 2000.0}
  - code:   基金代码
  - shares: 持有份额
  - cost:   总投入本金（元）

性能优化:
  - get_portfolio_with_valuation() 异步整合 "取持仓 + 并行估值"，
    配合 valuation_service 的 asyncio.gather + TTLCache 实现高性能
"""
from __future__ import annotations

from typing import List, Dict

from sqlalchemy.orm import Session

from app.models import Holding


def get_holdings(db: Session, user_id: int) -> List[Dict]:
    """
    获取指定用户的所有持仓

    Returns:
        [{"code": "005963", "shares": 1000.0, "cost": 2000.0}, ...]
    """
    rows = db.query(Holding).filter(Holding.user_id == user_id).all()
    return [r.to_dict() for r in rows]


def add_holding(db: Session, user_id: int, code: str, shares: float, cost: float) -> Dict:
    """
    添加或更新持仓

    Args:
        db:     数据库 Session
        user_id: 当前用户 ID
        code:   6 位基金代码
        shares: 持有份额
        cost:   总投入本金（元）

    Returns:
        {"success": True/False, ...}
    """
    try:
        existing = (
            db.query(Holding)
            .filter(Holding.user_id == user_id, Holding.code == code)
            .first()
        )

        if existing:
            existing.shares = shares
            existing.cost_price = cost
            action = "updated"
        else:
            new_holding = Holding(
                user_id=user_id, code=code, shares=shares, cost_price=cost,
            )
            db.add(new_holding)
            action = "added"

        db.commit()
        return {"success": True, "action": action, "code": code,
                "shares": shares, "cost": cost}

    except Exception as e:
        db.rollback()
        print(f"[ERROR] 添加持仓失败: {e}")
        return {"success": False, "error": str(e)}


def remove_holding(db: Session, user_id: int, code: str) -> Dict:
    """
    删除持仓（同时删除相关交易记录）

    Args:
        db:     数据库 Session
        user_id: 当前用户 ID
        code:   6 位基金代码

    Returns:
        {"success": True/False, ...}
    """
    try:
        from app.models import FundTransaction
        
        # 删除 Holding 记录
        row = (
            db.query(Holding)
            .filter(Holding.user_id == user_id, Holding.code == code)
            .first()
        )
        if row:
            db.delete(row)
        
        # 同时删除该基金的所有交易记录
        db.query(FundTransaction).filter(
            FundTransaction.user_id == user_id,
            FundTransaction.fund_code == code
        ).delete()
        
        db.commit()
        return {"success": True, "action": "removed", "code": code}

    except Exception as e:
        db.rollback()
        print(f"[ERROR] 删除持仓失败: {e}")
        return {"success": False, "error": str(e)}


def clear_holdings(db: Session, user_id: int) -> Dict:
    """清空指定用户的所有持仓"""
    try:
        db.query(Holding).filter(Holding.user_id == user_id).delete()
        db.commit()
        return {"success": True, "action": "cleared"}
    except Exception as e:
        db.rollback()
        print(f"[ERROR] 清空持仓失败: {e}")
        return {"success": False, "error": str(e)}


# ------------------------------------------------------------------
#  组合估值（整合 DB 查询 + 并行估值 + 缓存）
# ------------------------------------------------------------------

def get_portfolio_with_valuation(db: Session, user_id: int) -> dict:
    """
    一站式获取用户持仓估值看板（同步入口，内部调用异步估值）

    流程:
      1. 从数据库读取用户持仓列表（同步）
      2. 调用异步 get_portfolio_valuation（内部
         使用 asyncio.gather + aiohttp + TTLCache 并行计算）

    Returns:
        {
            "total_market_value": ...,
            "total_cost": ...,
            "total_profit": ...,
            "total_profit_rate": ...,
            "total_daily_profit": ...,
            "total_daily_profit_rate": ...,
            "funds": [ ... ]
        }
    """
    holdings = get_holdings(db, user_id)
    if not holdings:
        return {
            "total_market_value": 0, "total_cost": 0,
            "total_profit": 0, "total_profit_rate": 0,
            "total_daily_profit": 0, "total_daily_profit_rate": 0,
            "funds": [],
        }

    from app.services.valuation_service import get_portfolio_valuation
    # get_portfolio_valuation 是 async 函数，
    # 由 main.py 的 async 路由 await 调用
    return get_portfolio_valuation(holdings)


async def get_portfolio_with_valuation_async(db: Session, user_id: int) -> dict:
    """
    异步版：一站式获取用户持仓估值看板

    供 async def 路由直接 await 调用。
    """
    holdings = get_holdings(db, user_id)
    if not holdings:
        return {
            "total_market_value": 0, "total_cost": 0,
            "total_profit": 0, "total_profit_rate": 0,
            "total_daily_profit": 0, "total_daily_profit_rate": 0,
            "funds": [],
        }

    from app.services.valuation_service import get_portfolio_valuation
    return await get_portfolio_valuation(holdings)
