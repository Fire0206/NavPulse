"""
持仓管理路由
处理用户基金持仓的增删查 + OCR 截图导入
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import HoldingRequest
from app.services.auth_service import get_current_user
from app.services.portfolio_service import (
    remove_holding,
    get_portfolio_with_valuation_async,
)
from app.state import global_cache
from app.services.trading_calendar import is_market_open

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["持仓管理"])


@router.get("")
async def get_portfolio(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    force_refresh: bool = False,
):
    """
    获取持仓看板数据 API（仅返回当前用户的持仓）
    优先从缓存读取，休市时仍查数据库（只是不做实时估值爬取）
    """
    # 优先从缓存读取
    if not force_refresh:
        cached = global_cache.get_portfolio(current_user.id)
        if cached and cached.get("funds"):
            return cached

    # 无论是否开市，都尝试获取持仓数据
    try:
        result = await get_portfolio_with_valuation_async(db, current_user.id)
        global_cache.update_portfolio(current_user.id, result)
        if force_refresh:
            global_cache._update_timestamp()
        return result
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail=f"获取持仓数据失败: {str(e)}")


@router.post("")
async def add_portfolio_holding(
    holding: HoldingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    懒人初始化: 添加持仓

    用户提供 market_value (当前市值) + profit (盈亏)，
    系统自动计算:
      shares    = market_value / latest_nav
      total_cost = market_value - profit   (即投入本金)
    创建 type="init" 的交易记录，_sync_holding 自动同步 Holding 表。
    """
    try:
        from app.services.fund_service import _sync_get_fund_history, get_fund_name
        from app.services.transaction_service import add_transaction
        import asyncio

        if not holding.code or len(holding.code) != 6:
            raise HTTPException(status_code=400,
                                detail="基金代码格式错误，应为6位数字")

        # ── 兼容旧字段: amount → market_value ──
        market_value = holding.market_value
        if market_value <= 0 and holding.amount > 0:
            market_value = holding.amount
        if market_value <= 0:
            raise HTTPException(status_code=400,
                                detail="持仓市值必须大于0")

        profit = holding.profit  # 可以为负

        # 计算投入本金
        total_cost = market_value - profit
        if total_cost <= 0:
            raise HTTPException(status_code=400,
                                detail="投入本金必须大于0 (市值-收益)")

        # ── 获取最新净值 ──
        history = await asyncio.to_thread(_sync_get_fund_history, holding.code, 30)
        if not history:
            raise HTTPException(status_code=400,
                                detail="无法获取基金净值，请检查基金代码")
        latest_nav = history[-1]["nav"]
        if latest_nav <= 0:
            raise HTTPException(status_code=400,
                                detail="基金净值异常")

        # ── 核心公式 ──
        shares = round(market_value / latest_nav, 2)
        unit_cost = round(total_cost / shares, 4) if shares > 0 else 0

        # 建仓日期（用户指定 or 今天）
        init_date = holding.first_buy_date
        if not init_date:
            init_date = datetime.now().strftime("%Y-%m-%d")

        # ── 创建 INIT 交易记录 ──
        result = add_transaction(
            db, current_user.id, holding.code,
            tx_type="init",
            tx_date=init_date,
            shares=shares,
            amount=total_cost,
            nav=latest_nav,
        )

        if result.get("success"):
            global_cache.clear_portfolio_cache(current_user.id)
            # 异步获取基金名称（供前端乐观更新使用）
            try:
                fund_name = await asyncio.to_thread(get_fund_name, holding.code)
            except Exception:
                fund_name = holding.code
            return {
                "success": True,
                "message": "持仓已添加",
                "data": {
                    "code": holding.code,
                    "name": fund_name,
                    "market_value": market_value,
                    "profit": profit,
                    "total_cost": total_cost,
                    "shares": shares,
                    "unit_cost": unit_cost,
                    "nav": latest_nav,
                    "date": init_date,
                }
            }
        raise HTTPException(status_code=500, detail=result.get("error", "添加持仓失败"))
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail=f"添加持仓失败: {str(e)}")


@router.delete("/{fund_code}")
async def delete_portfolio_holding(
    fund_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除持仓（当前用户）"""
    try:
        if not fund_code or len(fund_code) != 6:
            raise HTTPException(status_code=400,
                                detail="基金代码格式错误，应为6位数字")
        result = remove_holding(db, current_user.id, fund_code)
        if result.get("success"):
            global_cache.clear_portfolio_cache(current_user.id)
            return {"success": True, "message": "持仓已删除",
                    "data": {"code": fund_code}}
        raise HTTPException(status_code=404, detail="未找到该持仓")
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail=f"删除持仓失败: {str(e)}")


# ═══════════════════════════════════════════════════════
#  OCR 截图导入
# ═══════════════════════════════════════════════════════

@router.post("/ocr-parse")
async def ocr_parse_screenshot(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    上传支付宝持仓截图，OCR 识别并返回解析结果。
    前端以此展示预览表格供用户确认。
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片大小不能超过 10MB")

    try:
        import asyncio
        from app.services.ocr_service import parse_alipay_screenshot

        # OCR 是 CPU 密集型同步操作，必须放到线程池避免阻塞事件循环
        loop = asyncio.get_event_loop()
        funds = await loop.run_in_executor(
            None, parse_alipay_screenshot, image_bytes
        )
        return {"success": True, "funds": funds, "count": len(funds)}
    except RuntimeError as e:
        # rapidocr 未安装
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"OCR 解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=500,
                            detail=f"OCR 识别失败: {str(e)}")


@router.post("/batch-import")
async def batch_import_holdings(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    批量导入持仓（配合 OCR 识别结果使用）。

    payload: {
        "funds": [
            {"code": "007871", "market_value": 1631.94, "profit": -119.36},
            ...
        ]
    }
    """
    from app.services.fund_service import _sync_get_fund_history
    from app.services.transaction_service import add_transaction
    import asyncio

    funds = payload.get("funds", [])
    if not funds:
        raise HTTPException(status_code=400, detail="没有需要导入的基金")

    results = []
    success_count = 0

    for item in funds:
        code = str(item.get("code", "")).strip()
        market_value = float(item.get("market_value", 0))
        profit = float(item.get("profit", 0))

        if not code or len(code) != 6:
            results.append({"code": code, "success": False,
                            "error": "基金代码格式错误"})
            continue
        if market_value <= 0:
            results.append({"code": code, "success": False,
                            "error": "市值必须大于 0"})
            continue

        total_cost = market_value - profit
        if total_cost <= 0:
            results.append({"code": code, "success": False,
                            "error": "投入本金 ≤ 0"})
            continue

        try:
            history = await asyncio.to_thread(_sync_get_fund_history, code, 30)
            if not history:
                results.append({"code": code, "success": False,
                                "error": "无法获取基金净值"})
                continue

            latest_nav = history[-1]["nav"]
            if latest_nav <= 0:
                results.append({"code": code, "success": False,
                                "error": "基金净值异常"})
                continue

            shares = round(market_value / latest_nav, 2)
            init_date = datetime.now().strftime("%Y-%m-%d")

            tx_result = add_transaction(
                db, current_user.id, code,
                tx_type="init",
                tx_date=init_date,
                shares=shares,
                amount=total_cost,
                nav=latest_nav,
            )

            if tx_result.get("success"):
                success_count += 1
                results.append({"code": code, "success": True})
            else:
                results.append({"code": code, "success": False,
                                "error": tx_result.get("error", "导入失败")})
        except Exception as e:
            results.append({"code": code, "success": False,
                            "error": str(e)})

    # 清除持仓缓存以便重新加载
    if success_count > 0:
        global_cache.clear_portfolio_cache(current_user.id)

    return {
        "success": True,
        "total": len(funds),
        "imported": success_count,
        "failed": len(funds) - success_count,
        "results": results,
    }
