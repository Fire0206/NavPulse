"""
全局状态容器 + SQLite 持久化
内存缓存供 API 秒级读取，同时将数据落盘到 SQLite，
服务器重启后自动恢复上次数据（无需重新爬取历史）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("navpulse.state")


class GlobalCache:
    """
    全局缓存数据容器

    写入流程: 调度器 → update_xxx() → 内存 + SQLite 双写
    读取流程: API → get_xxx() → 纯内存读取 (< 1ms)
    启动流程: load_from_db() → 从 SQLite 恢复到内存
    """

    def __init__(self):
        # 大盘指数数据
        self.market_indices: list[dict[str, Any]] = []
        # 涨跌分布数据
        self.stock_distribution: dict[str, Any] = {}
        # 板块数据
        self.sectors: list[dict[str, Any]] = []
        # 基金估值缓存 {fund_code: valuation_data}
        self.fund_valuations: dict[str, dict[str, Any]] = {}
        # 用户持仓估值缓存 {user_id: portfolio_data}
        self.portfolio_cache: dict[int, dict[str, Any]] = {}
        # 最后更新时间
        self.last_update_time: str = "未更新"
        # 调度器运行状态
        self.scheduler_running: bool = False

    # ══════════════════════════════════════════════════════
    #  内存写入 + 持久化
    # ══════════════════════════════════════════════════════

    def update_market_data(
        self,
        indices: list[dict[str, Any]] | None = None,
        distribution: dict[str, Any] | None = None,
        sectors: list[dict[str, Any]] | None = None,
    ):
        """更新行情数据 → 内存 + SQLite"""
        if indices is not None:
            self.market_indices = indices
        if distribution is not None:
            self.stock_distribution = distribution
        if sectors is not None:
            self.sectors = sectors
        self._update_timestamp()
        # 持久化
        self._persist_market()

    def update_fund_valuation(self, fund_code: str, data: dict[str, Any]):
        """更新单只基金估值 → 内存 + SQLite"""
        self.fund_valuations[fund_code] = data
        self._persist_fund_valuation(fund_code, data)

    def update_portfolio(self, user_id: int, data: dict[str, Any]):
        """更新用户持仓数据 → 内存 + SQLite"""
        self.portfolio_cache[user_id] = data
        self._persist_portfolio(user_id, data)

    # ══════════════════════════════════════════════════════
    #  内存读取 (API 使用)
    # ══════════════════════════════════════════════════════

    def get_fund_valuation(self, fund_code: str) -> dict[str, Any] | None:
        return self.fund_valuations.get(fund_code)

    def get_portfolio(self, user_id: int) -> dict[str, Any] | None:
        return self.portfolio_cache.get(user_id)

    def get_market_data(self) -> dict[str, Any]:
        return {
            "indices": self.market_indices,
            "distribution": self.stock_distribution,
            "sectors": self.sectors,
            "last_update_time": self.last_update_time,
        }

    # ══════════════════════════════════════════════════════
    #  启动恢复：从 SQLite 加载到内存
    # ══════════════════════════════════════════════════════

    def load_from_db(self):
        """
        启动时调用：从 SQLite 恢复所有缓存数据到内存
        这样即使休市，页面也能立即展示上一交易日的数据
        """
        try:
            from app.database import SessionLocal
            from app.models import CachedData, CachedFundValuation, CachedPortfolio

            db = SessionLocal()
            try:
                # 恢复行情数据
                for key in ("market_indices", "stock_distribution", "sectors", "last_update_time"):
                    row = db.query(CachedData).filter(CachedData.key == key).first()
                    if row:
                        val = json.loads(row.value)
                        if key == "market_indices":
                            self.market_indices = val
                        elif key == "stock_distribution":
                            self.stock_distribution = val
                        elif key == "sectors":
                            self.sectors = val
                        elif key == "last_update_time":
                            self.last_update_time = val

                # 恢复基金估值
                for row in db.query(CachedFundValuation).all():
                    try:
                        self.fund_valuations[row.fund_code] = json.loads(row.data)
                    except Exception:
                        pass

                # 恢复用户持仓
                for row in db.query(CachedPortfolio).all():
                    try:
                        self.portfolio_cache[row.user_id] = json.loads(row.data)
                    except Exception:
                        pass

                loaded = (
                    f"指数{len(self.market_indices)}条, "
                    f"基金估值{len(self.fund_valuations)}条, "
                    f"用户持仓{len(self.portfolio_cache)}条"
                )
                logger.info(f"[OK] 从 SQLite 恢复缓存: {loaded}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[WARN] 从 SQLite 恢复缓存失败: {e}")

    # ══════════════════════════════════════════════════════
    #  内部持久化方法
    # ══════════════════════════════════════════════════════

    def _persist_market(self):
        """将行情数据写入 SQLite"""
        try:
            from app.database import SessionLocal
            from app.models import CachedData

            db = SessionLocal()
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for key, val in [
                    ("market_indices", self.market_indices),
                    ("stock_distribution", self.stock_distribution),
                    ("sectors", self.sectors),
                    ("last_update_time", self.last_update_time),
                ]:
                    row = db.query(CachedData).filter(CachedData.key == key).first()
                    json_val = json.dumps(val, ensure_ascii=False)
                    if row:
                        row.value = json_val
                        row.updated_at = now
                    else:
                        db.add(CachedData(key=key, value=json_val, updated_at=now))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"持久化行情失败: {e}")

    def _persist_fund_valuation(self, fund_code: str, data: dict):
        """将单只基金估值写入 SQLite"""
        try:
            from app.database import SessionLocal
            from app.models import CachedFundValuation

            db = SessionLocal()
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                json_val = json.dumps(data, ensure_ascii=False)
                row = db.query(CachedFundValuation).filter(
                    CachedFundValuation.fund_code == fund_code
                ).first()
                if row:
                    row.data = json_val
                    row.updated_at = now
                else:
                    db.add(CachedFundValuation(
                        fund_code=fund_code, data=json_val, updated_at=now
                    ))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"持久化基金估值失败: {e}")

    def _persist_portfolio(self, user_id: int, data: dict):
        """将用户持仓写入 SQLite"""
        try:
            from app.database import SessionLocal
            from app.models import CachedPortfolio

            db = SessionLocal()
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                json_val = json.dumps(data, ensure_ascii=False)
                row = db.query(CachedPortfolio).filter(
                    CachedPortfolio.user_id == user_id
                ).first()
                if row:
                    row.data = json_val
                    row.updated_at = now
                else:
                    db.add(CachedPortfolio(
                        user_id=user_id, data=json_val, updated_at=now
                    ))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"持久化用户持仓失败: {e}")

    # ══════════════════════════════════════════════════════
    #  工具方法
    # ══════════════════════════════════════════════════════

    def _update_timestamp(self):
        self.last_update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def clear_portfolio_cache(self, user_id: int = None):
        if user_id is not None:
            self.portfolio_cache.pop(user_id, None)
        else:
            self.portfolio_cache.clear()

    def get_status(self) -> dict[str, Any]:
        return {
            "scheduler_running": self.scheduler_running,
            "last_update_time": self.last_update_time,
            "market_indices_count": len(self.market_indices),
            "fund_valuations_count": len(self.fund_valuations),
            "portfolio_cache_count": len(self.portfolio_cache),
        }


# 全局单例
global_cache = GlobalCache()
