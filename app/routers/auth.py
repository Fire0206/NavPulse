"""
认证 & 页面路由
处理登录/注册页面渲染 + 认证 API + 首页
"""
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import RegisterRequest
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
    get_user_by_username,
    validate_password_strength,
)

router = APIRouter()

# 模板引擎
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

import os
_ICP_RECORD = os.environ.get("ICP_RECORD", "")


# ==================== 页面路由 ====================

@router.get("/")
async def index(request: Request):
    """首页路由 - 渲染前端页面"""
    try:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "icp_record": _ICP_RECORD,
        })
    except Exception as e:
        print(f"[ERROR] 渲染模板失败: {e}")
        return JSONResponse(status_code=500,
                            content={"error": f"模板加载失败: {str(e)}"})


@router.get("/login")
async def login_page(request: Request):
    """登录页"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/register")
async def register_page(request: Request):
    """注册页"""
    return templates.TemplateResponse("register.html", {"request": request})


# ==================== 认证 API ====================

@router.post("/register")
async def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """用户注册 API（成功后直接返回 JWT，实现注册即登录）"""
    username = req.username.strip()
    password = req.password.strip()

    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="用户名至少 3 个字符")
    if len(username) > 32:
        raise HTTPException(status_code=400, detail="用户名最多 32 个字符")
    
    # 密码强度校验
    is_valid, error_msg = validate_password_strength(password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 检查用户名是否已存在（模糊化错误信息，防止用户名枚举）
    if get_user_by_username(db, username):
        raise HTTPException(status_code=400, detail="用户名已存在，请更换后重试")

    user = create_user(db, username, password)
    token = create_access_token(data={"sub": user.username})
    return {
        "success": True,
        "message": "注册成功",
        "username": user.username,
        "access_token": token,
        "token_type": "bearer",
        "redirect_to": "/",
    }


@router.post("/token")
async def login_for_token(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """
    用户登录 API - 返回 JWT Token
    增强版：速率限制 + 模糊化错误
    """
    client_ip = request.client.host if request.client else "unknown"
    
    try:
        user = authenticate_user(db, req.username.strip(), req.password.strip(), client_ip)
    except HTTPException:
        # 速率限制异常直接向上抛
        raise
    
    if not user:
        # 模糊化错误：不区分"用户名不存在"和"密码错误"
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = create_access_token(data={"sub": user.username})
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
    }


@router.get("/api/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return {"username": current_user.username}
