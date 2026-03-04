"""
自选基金路由
处理用户自选基金的增删查
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Watchlist
from app.schemas import WatchlistRequest
from app.services.auth_service import get_current_user
from app.services.valuation_service import calculate_fund_estimate
from app.state import global_cache
from app.services.trading_calendar import is_market_open

router = APIRouter(prefix="/api/watchlist", tags=["自选基金"])


@router.get("")
async def get_watchlist(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户自选基金列表（带实时估值，休市时从缓存读取）"""
    try:
        watchlist = db.query(Watchlist).filter(
            Watchlist.user_id == current_user.id
        ).all()

        if not watchlist:
            return {"funds": [], "count": 0}

        fund_codes = [w.fund_code for w in watchlist]
        trading = is_market_open()

        async def get_fund_info(code: str):
            cached = global_cache.get_fund_valuation(code)
            # 休市时 + 缓存有效（无 error 且 estimate_change 不为 0） → 直接返回
            if (cached and not trading
                    and "error" not in cached
                    and cached.get("estimate_change", 0) != 0):
                return {
                    "code": code,
                    "name": cached.get("fund_name", code),
                    "estimate_change": cached.get("estimate_change", 0),
                    "data_date": cached.get("data_date"),
                    "fund_type": cached.get("fund_type", ""),
                    "fund_type_label": cached.get("fund_type_label", ""),
                    "estimation_method": cached.get("estimation_method", ""),
                }
            # 其它情况（开盘中 / 缓存无效 / 缓存值为0） → 重新计算
            try:
                result = await calculate_fund_estimate(code)
                return {
                    "code": code,
                    "name": result.get("fund_name", code),
                    "estimate_change": result.get("estimate_change", 0),
                    "data_date": result.get("data_date"),
                    "fund_type": result.get("fund_type", ""),
                    "fund_type_label": result.get("fund_type_label", ""),
                    "estimation_method": result.get("estimation_method", ""),
                }
            except Exception:
                if cached:
                    return {
                        "code": code,
                        "name": cached.get("fund_name", code),
                        "estimate_change": cached.get("estimate_change", 0),
                        "data_date": cached.get("data_date"),
                        "fund_type": cached.get("fund_type", ""),
                        "fund_type_label": cached.get("fund_type_label", ""),
                    }
                return {
                    "code": code,
                    "name": code,
                    "estimate_change": 0,
                    "data_date": None,
                }

        tasks = [get_fund_info(code) for code in fund_codes]
        funds = await asyncio.gather(*tasks)

        # 如果有任何基金触发了重新计算，更新时间戳
        global_cache._update_timestamp()

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
