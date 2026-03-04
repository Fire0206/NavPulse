"""
路由模块
所有 API 路由按业务域拆分为独立模块
"""
from app.routers.auth import router as auth_router
from app.routers.portfolio import router as portfolio_router
from app.routers.watchlist import router as watchlist_router
from app.routers.market import router as market_router
from app.routers.fund import router as fund_router
from app.routers.system import router as system_router

__all__ = [
    "auth_router",
    "portfolio_router",
    "watchlist_router",
    "market_router",
    "fund_router",
    "system_router",
]
