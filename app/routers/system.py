"""
系统管理路由
处理健康检查、缓存管理、系统状态
"""
from fastapi import APIRouter

from app.services.valuation_service import get_cache_info, clear_cache
from app.state import global_cache
from app.scheduler import get_scheduler_status
from app.services.trading_calendar import get_trading_status

router = APIRouter(tags=["系统管理"])


@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "message": "NavPulse is running"}


@router.get("/api/cache")
async def cache_status():
    """查看当前缓存状态（调试 / 监控用）"""
    valuation_cache = get_cache_info()
    scheduler_status = get_scheduler_status()
    global_status = global_cache.get_status()
    return {
        "valuation_cache": valuation_cache,
        "scheduler": scheduler_status,
        "global_cache": global_status,
    }


@router.delete("/api/cache")
async def cache_clear():
    """手动清空估值缓存"""
    clear_cache()
    global_cache.fund_valuations.clear()
    global_cache.portfolio_cache.clear()
    return {"success": True, "message": "缓存已清空"}


@router.get("/api/status")
async def get_system_status():
    """
    获取系统状态（调度器 + 最后更新 + 交易状态）
    供前端显示数据更新状态和休市提示
    """
    trading = get_trading_status()
    return {
        "last_update_time": global_cache.last_update_time,
        "scheduler_running": global_cache.scheduler_running,
        "scheduler": get_scheduler_status(),
        "trading": trading,
    }
