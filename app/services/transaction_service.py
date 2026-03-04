"""
交易记录服务 — 管理基金交易、计算持仓统计

三种交易类型:
  - init: 懒人初始化 — 用户提供当前市值+收益，系统反推份额和单位成本
          total_shares = market_value / nav
          total_cost   = market_value - profit  (即投入本金)
  - buy:  加仓 — 加权平均成本
          new_unit_cost = (old_shares × old_unit_cost + buy_amount) / (old_shares + new_shares)
  - sell: 减仓 — 单位成本不变
          total_shares -= sell_shares
          total_cost = unit_cost × remaining_shares

存储约定:
  FundTransaction.amount  对于 init = 投入本金 (market_value - profit)
                          对于 buy  = 买入金额
                          对于 sell = 赎回金额
  FundTransaction.shares  交易份额 (init/buy/sell 均必填)
  FundTransaction.nav     交易时净值
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models import FundTransaction, Holding


# ══════════════════════════════════════════════════════════
#  CRUD
# ══════════════════════════════════════════════════════════

def get_transactions(db: Session, user_id: int, fund_code: str) -> List[Dict]:
    """获取某基金的全部交易记录（按日期升序）"""
    rows = (
        db.query(FundTransaction)
        .filter(FundTransaction.user_id == user_id,
                FundTransaction.fund_code == fund_code)
        .order_by(FundTransaction.date.asc(), FundTransaction.id.asc())
        .all()
    )
    return [r.to_dict() for r in rows]


def add_transaction(
    db: Session,
    user_id: int,
    fund_code: str,
    tx_type: str,
    tx_date: str,
    shares: float,
    amount: float,
    nav: float = 0,
) -> Dict:
    """
    添加交易记录并同步更新 Holding 表

    Args:
        tx_type: "init" | "buy" | "sell"
        tx_date: "YYYY-MM-DD"
        shares:  交易份额
        amount:  交易金额 (元)  —  init时为投入本金
        nav:     成交净值 (可不填)
    """
    try:
        if tx_type not in ("init", "buy", "sell"):
            return {"success": False, "error": "type 必须是 init / buy / sell"}

        # init 类型：一个基金只允许一条 init 记录（如有则替换）
        if tx_type == "init":
            existing_init = (
                db.query(FundTransaction)
                .filter(
                    FundTransaction.user_id == user_id,
                    FundTransaction.fund_code == fund_code,
                    FundTransaction.type == "init",
                )
                .first()
            )
            if existing_init:
                existing_init.date = tx_date
                existing_init.shares = shares
                existing_init.amount = amount
                existing_init.nav = nav
                existing_init.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.flush()
                _sync_holding(db, user_id, fund_code)
                db.commit()
                return {"success": True, "id": existing_init.id}

        tx = FundTransaction(
            user_id=user_id,
            fund_code=fund_code,
            type=tx_type,
            date=tx_date,
            shares=shares,
            amount=amount,
            nav=nav if nav else round(amount / shares, 4) if shares > 0 else 0,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        db.add(tx)
        db.flush()

        # 根据全部交易记录重算持仓
        _sync_holding(db, user_id, fund_code)

        db.commit()
        return {"success": True, "id": tx.id}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}


def delete_transaction(db: Session, user_id: int, tx_id: int) -> Dict:
    """删除交易记录并同步更新 Holding 表"""
    try:
        tx = (
            db.query(FundTransaction)
            .filter(FundTransaction.id == tx_id,
                    FundTransaction.user_id == user_id)
            .first()
        )
        if not tx:
            return {"success": False, "error": "记录不存在"}

        fund_code = tx.fund_code
        db.delete(tx)
        db.flush()

        _sync_holding(db, user_id, fund_code)

        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════
#  核心: 交易回放 → 持仓快照
# ══════════════════════════════════════════════════════════

def _replay_transactions(txs) -> tuple[float, float]:
    """
    按时间顺序回放交易列表，返回 (total_shares, total_cost)

    规则:
      init → 重置 total_shares / total_cost (快照)
      buy  → total_shares += new, total_cost += amount (加权)
      sell → total_shares -= sold, total_cost -= sold * unit_cost (成本不变)
    """
    total_shares = 0.0
    total_cost = 0.0

    for tx in txs:
        if tx.type == "init":
            # 快照: 覆盖为 init 的份额和投入本金
            total_shares = tx.shares
            total_cost = tx.amount
        elif tx.type == "buy":
            total_shares += tx.shares
            total_cost += tx.amount
        elif tx.type == "sell":
            if total_shares > 0:
                unit_cost = total_cost / total_shares
                sell_shares = min(tx.shares, total_shares)
                total_shares -= sell_shares
                total_cost = unit_cost * total_shares

    total_shares = max(0, round(total_shares, 4))
    total_cost = max(0, round(total_cost, 2))
    return total_shares, total_cost


# ══════════════════════════════════════════════════════════
#  持仓同步 (交易记录 → Holding 表)
# ══════════════════════════════════════════════════════════

def _sync_holding(db: Session, user_id: int, fund_code: str):
    """
    根据全部交易记录重新计算持仓，更新 Holding 表
    支持 init / buy / sell 三种类型
    """
    txs = (
        db.query(FundTransaction)
        .filter(FundTransaction.user_id == user_id,
                FundTransaction.fund_code == fund_code)
        .order_by(FundTransaction.date.asc(), FundTransaction.id.asc())
        .all()
    )

    total_shares, total_cost = _replay_transactions(txs)

    holding = (
        db.query(Holding)
        .filter(Holding.user_id == user_id, Holding.code == fund_code)
        .first()
    )

    if total_shares > 0:
        if holding:
            holding.shares = total_shares
            holding.cost_price = total_cost
        else:
            db.add(Holding(
                user_id=user_id, code=fund_code,
                shares=total_shares, cost_price=total_cost,
            ))
    else:
        if holding:
            db.delete(holding)


# ══════════════════════════════════════════════════════════
#  持仓统计计算
# ══════════════════════════════════════════════════════════

def calculate_holding_stats(db: Session, user_id: int, fund_code: str) -> Dict:
    """
    计算持仓详细统计:
      - total_shares:       总持有份额
      - total_cost:         总投入成本 (unit_cost × shares)
      - avg_cost_per_share: 单位成本 (元/份)
      - holding_days:       持有天数
      - first_buy_date:     首次建仓日期
      - transactions:       全部交易记录列表
    """
    txs = (
        db.query(FundTransaction)
        .filter(FundTransaction.user_id == user_id,
                FundTransaction.fund_code == fund_code)
        .order_by(FundTransaction.date.asc(), FundTransaction.id.asc())
        .all()
    )

    if not txs:
        # 没有交易记录时，从 Holding 读取遗留数据
        holding = (
            db.query(Holding)
            .filter(Holding.user_id == user_id, Holding.code == fund_code)
            .first()
        )
        if holding:
            return {
                "has_holding": True,
                "total_shares": holding.shares,
                "total_cost": holding.cost_price,
                "avg_cost_per_share": round(holding.cost_price / holding.shares, 4) if holding.shares > 0 else 0,
                "holding_days": 0,
                "first_buy_date": None,
                "transactions": [],
            }
        return {"has_holding": False, "transactions": []}

    total_shares, total_cost = _replay_transactions(txs)
    avg = round(total_cost / total_shares, 4) if total_shares > 0 else 0

    # 首次建仓日期 = 第一条 init 或 buy 的日期
    first_date = None
    for tx in txs:
        if tx.type in ("init", "buy"):
            first_date = tx.date
            break

    holding_days = 0
    if first_date:
        try:
            holding_days = (datetime.now() - datetime.strptime(first_date, "%Y-%m-%d")).days
        except Exception:
            pass

    return {
        "has_holding": total_shares > 0,
        "total_shares": total_shares,
        "total_cost": total_cost,
        "avg_cost_per_share": avg,
        "holding_days": holding_days,
        "first_buy_date": first_date,
        "transactions": [t.to_dict() for t in txs],
    }
