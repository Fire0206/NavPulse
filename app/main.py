"""
NavPulse - 基金实时估值系统主入口
应用工厂 + 路由注册 + 生命周期管理
"""
import os
from pathlib import Path
from contextlib import asynccontextmanager

# ── 加载 .env 文件（如果存在）──
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv 为可选依赖

DEBUG = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

# ── 禁用系统代理（全局）────────────────────────────────────
# akshare 直连国内金融数据源（东方财富等），经过代理会断连
# 同时清掉环境变量代理 和 Windows 注册表代理（requests trust_env）
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)

import requests as _req
if not getattr(_req.Session, "_navpulse_no_proxy_patched", False):
    _orig_init = _req.Session.__init__
    def _patched_init(self, *args, _orig=_orig_init, **kwargs):
        _orig(self, *args, **kwargs)
        self.trust_env = False   # 不读系统代理 / 注册表代理
    _req.Session.__init__ = _patched_init
    _req.Session._navpulse_no_proxy_patched = True
# ─────────────────────────────────────────────────────────

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from app.database import init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.routers import (
    auth_router,
    portfolio_router,
    watchlist_router,
    market_router,
    fund_router,
    system_router,
)

# ==================== Lifespan ====================

@asynccontextmanager
async def lifespan(app):
    """FastAPI 生命周期：启动时初始化 DB + 调度器 + OCR 预热，关闭时停止调度器"""
    init_db()
    await start_scheduler()
    # OCR 引擎预热（后台线程避免阻塞启动）
    import threading
    def _warmup():
        try:
            from app.services.ocr_service import warmup_ocr_engine
            warmup_ocr_engine()
        except Exception:
            pass
    threading.Thread(target=_warmup, daemon=True).start()
    yield
    stop_scheduler()


# ==================== 创建应用 ====================

# 生产环境关闭 Swagger 文档
app = FastAPI(
    title="NavPulse Real-time Valuation",
    description="基金实时估值系统 API（多用户版）",
    version="5.0.0",
    lifespan=lifespan,
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None,
)

# CORS — 从环境变量读取允许的域名（逗号分隔），默认仅允许同源
_cors_origins = [
    o.strip() for o in
    os.environ.get("CORS_ORIGINS", "*").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 安全响应头中间件（适配开源项目与生产环境）
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        # X-Content-Type-Options: 防止 MIME 类型嗅探
        response.headers["X-Content-Type-Options"] = "nosniff"
        # X-Frame-Options: 防止点击劫持
        response.headers["X-Frame-Options"] = "DENY"
        # X-XSS-Protection: 启用浏览器 XSS 过滤
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer-Policy: 控制 Referer 信息泄露
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions-Policy: 限制浏览器功能访问
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # 生产环境启用 HSTS（强制 HTTPS）
        if _IS_PRODUCTION := (os.environ.get("ENVIRONMENT", "development").lower() == "production"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# 开发模式：为 JS 文件禁用浏览器缓存
if DEBUG:
    class NoCacheJSMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/static/") and request.url.path.endswith(".js"):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response

    app.add_middleware(NoCacheJSMiddleware)

# ==================== 静态文件 ====================

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

if STATIC_DIR.exists() and STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    print(f"[OK] 静态文件目录已挂载: {STATIC_DIR}")
else:
    print(f"[WARN] 静态文件目录不存在，跳过挂载: {STATIC_DIR}")

# ==================== 注册路由 ====================

app.include_router(auth_router)
app.include_router(portfolio_router)
app.include_router(watchlist_router)
app.include_router(market_router)
app.include_router(fund_router)
app.include_router(system_router)

# ==================== 启动入口（仅本地开发） ====================

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=DEBUG,
    )
