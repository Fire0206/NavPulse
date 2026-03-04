"""
行情数据路由
处理大盘指数、涨跌分布、板块、基金涨跌榜

策略：API 始终立即返回 global_cache 数据（秒级响应），
     需要刷新时通过 asyncio.create_task 在后台静默爬取，
     爬取完成后自动写入缓存，下次请求即可拿到最新数据。
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.market_service import (
    get_market_indices,
    get_stock_distribution,
    get_sector_list,
    get_full_market_data,
    get_fund_rank,
)
from app.state import global_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["行情数据"])

# 后台刷新锁：防止同时触发多个爬取任务
_bg_refreshing = False


async def _background_market_refresh():
    """后台静默刷新行情数据（不阻塞任何 API 响应）"""
    global _bg_refreshing
    if _bg_refreshing:
        return  # 已有任务在跑，跳过
    _bg_refreshing = True
    try:
        data = await get_full_market_data()
        global_cache.update_market_data(
            indices=data.get("indices"),
            distribution=data.get("distribution"),
            sectors=data.get("sectors"),
        )
        logger.info("[BG-MARKET] 后台行情刷新完成")
    except Exception as e:
        logger.error(f"[BG-MARKET] 后台行情刷新失败: {e}")
    finally:
        _bg_refreshing = False


@router.get("")
async def get_market_data(force_refresh: bool = False):
    """
    获取行情数据（大盘指数 + 涨跌分布 + 板块列表）
    始终立即返回缓存数据（秒级响应），绝不阻塞请求。
    - 正常请求：直接返回 global_cache
    - force_refresh=true：触发后台异步刷新，仍立即返回当前缓存
    - 缓存为空（首次启动）：触发后台刷新，返回空结构
    """
    cached = global_cache.get_market_data()
    has_valid = cached["indices"] and any(x.get("price") for x in cached["indices"])

    if force_refresh:
        # 用户手动刷新 → 后台异步爬取，立即返回当前数据
        asyncio.create_task(_background_market_refresh())
        return cached

    if has_valid:
        return cached

    # 完全无缓存（首次启动、调度器尚未执行） → 触发后台刷新，返回空结构
    asyncio.create_task(_background_market_refresh())
    return cached


@router.get("/indices")
async def get_indices():
    """获取大盘指数（优先缓存，缓存为空触发后台刷新）"""
    if global_cache.market_indices and any(x.get("price") for x in global_cache.market_indices):
        return global_cache.market_indices
    # 缓存为空 → 后台刷新，返回空列表
    asyncio.create_task(_background_market_refresh())
    return global_cache.market_indices or []


@router.get("/distribution")
async def get_distribution():
    """获取涨跌分布（优先缓存，缓存为空触发后台刷新）"""
    if global_cache.stock_distribution and global_cache.stock_distribution.get("total", 0) > 0:
        return global_cache.stock_distribution
    # 缓存为空 → 后台刷新，返回空结构
    asyncio.create_task(_background_market_refresh())
    return global_cache.stock_distribution or {}


@router.get("/sectors")
async def get_sectors():
    """获取板块列表（始终从 DB 读取，含实时估值加权涨跌幅）"""
    try:
        return await get_sector_list()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SectorIn(BaseModel):
    name: str = Field(..., description="板块名称（唯一键）")
    fund_codes: list[str] = Field(default_factory=list, description="该板块包含的基金代码列表")
    streak: int = Field(default=0, description="连涨天数（正=连涨，负=连跌）")
    sort_order: int = Field(default=0, description="排序权重，越大越靠前")


@router.post("/sectors", summary="新增或更新板块（手动维护）")
async def upsert_sector(body: SectorIn):
    """
    手动维护板块数据。不存在则新增，已存在则更新。
    fund_codes: 该板块包含的基金代码列表，用于计算板块涨跌幅
    """
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.database import SessionLocal
    from app.models import Sector

    db = SessionLocal()
    try:
        row = db.query(Sector).filter(Sector.name == body.name).first()
        now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
        if row:
            row.fund_codes = json.dumps(body.fund_codes, ensure_ascii=False)
            row.streak = body.streak
            row.sort_order = body.sort_order
            row.updated_at = now
        else:
            row = Sector(
                name=body.name,
                fund_codes=json.dumps(body.fund_codes, ensure_ascii=False),
                streak=body.streak,
                sort_order=body.sort_order,
                updated_at=now,
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        return {"ok": True, "sector": row.to_dict()}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/sectors/{sector_name}", summary="删除板块")
async def delete_sector(sector_name: str):
    """删除指定板块"""
    from app.database import SessionLocal
    from app.models import Sector

    db = SessionLocal()
    try:
        row = db.query(Sector).filter(Sector.name == sector_name).first()
        if not row:
            raise HTTPException(status_code=404, detail=f"板块 '{sector_name}' 不存在")
        db.delete(row)
        db.commit()
        return {"ok": True, "deleted": sector_name}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/fund-rank")
async def get_fund_rank_api():
    """
    获取基金涨跌榜（每日涨幅/跌幅 TOP50）
    数据缓存 300 秒，休市时显示上一个交易日的数据
    """
    try:
        result = await get_fund_rank()
        return result
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail=f"获取基金涨跌榜失败: {str(e)}")
