"""
自选基金路由
处理用户自选基金的增删查
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Watchlist
from app.schemas import WatchlistRequest
from app.services.auth_service import get_current_user
from app.services.valuation_service import calculate_fund_estimate
from app.state import global_cache
from app.services.trading_calendar import is_market_open

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watchlist", tags=["自选基金"])


@router.get("")
async def get_watchlist(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取用户自选基金列表（始终立即返回缓存数据，后台静默刷新）
    """
    try:
        watchlist = db.query(Watchlist).filter(
            Watchlist.user_id == current_user.id
        ).all()

        if not watchlist:
            return {"funds": [], "count": 0}

        fund_codes = [w.fund_code for w in watchlist]

        # ── 立即从缓存构建结果（毫秒级） ──
        funds = []
        need_refresh_codes = []
        for code in fund_codes:
            cached = global_cache.get_fund_valuation(code)
            if cached and "error" not in cached:
                funds.append({
                    "code": code,
                    "name": cached.get("fund_name", code),
                    "estimate_change": cached.get("estimate_change", 0),
                    "data_date": cached.get("data_date"),
                    "fund_type": cached.get("fund_type", ""),
                    "fund_type_label": cached.get("fund_type_label", ""),
                    "estimation_method": cached.get("estimation_method", ""),
                })
            else:
                # 无缓存 → 先返回空壳，后台刷新
                funds.append({
                    "code": code,
                    "name": code,
                    "estimate_change": 0,
                    "data_date": None,
                })
                need_refresh_codes.append(code)

        # ── 后台静默刷新缺失缓存的基金（不阻塞响应） ──
        if need_refresh_codes:
            async def _bg_refresh():
                for code in need_refresh_codes:
                    try:
                        result = await calculate_fund_estimate(code)
                        if "error" not in result:
                            global_cache.update_fund_valuation(code, result)
                    except Exception as e:
                        logger.warning("[BG-WATCH] %s 估值刷新失败: %s", code, e)
            asyncio.create_task(_bg_refresh())

        return {"funds": funds, "count": len(funds)}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail=f"获取自选列表失败: {str(e)}")


@router.post("")
async def add_to_watchlist(
    req: WatchlistRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """添加基金到自选"""
    try:
        code = req.code.strip()
        if not code or len(code) != 6:
            raise HTTPException(status_code=400,
                                detail="基金代码格式错误，应为6位数字")

        existing = db.query(Watchlist).filter(
            Watchlist.user_id == current_user.id,
            Watchlist.fund_code == code
        ).first()

        if existing:
            return {"success": True, "message": "该基金已在自选中"}

        new_item = Watchlist(user_id=current_user.id, fund_code=code)
        db.add(new_item)
        db.commit()

        return {"success": True, "message": "已添加到自选", "code": code}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail=f"添加自选失败: {str(e)}")


@router.delete("/{fund_code}")
async def remove_from_watchlist(
    fund_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从自选中删除基金"""
    try:
        if not fund_code or len(fund_code) != 6:
            raise HTTPException(status_code=400,
                                detail="基金代码格式错误，应为6位数字")

        result = db.query(Watchlist).filter(
            Watchlist.user_id == current_user.id,
            Watchlist.fund_code == fund_code
        ).delete()

        db.commit()

        if result:
            return {"success": True, "message": "已从自选中删除", "code": fund_code}
        raise HTTPException(status_code=404, detail="未找到该自选")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail=f"删除自选失败: {str(e)}")
