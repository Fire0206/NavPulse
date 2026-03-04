"""
认证服务
处理用户注册、登录、JWT Token 生成与校验
增强版：密码强度校验、速率限制、安全性加固
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

# ==================== 配置 ====================

import os
import secrets
import logging

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    logger.warning(
        "⚠️  JWT_SECRET_KEY 未配置！当前使用随机密钥，每次重启后所有 Token 失效。"
        "生产环境请在 .env 中设置 JWT_SECRET_KEY=<固定密钥>"
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("TOKEN_EXPIRE_MINUTES", "1440"))  # 默认 24h

# 生产环境检查
_IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development").lower() == "production"
if _IS_PRODUCTION and not os.environ.get("JWT_SECRET_KEY"):
    raise RuntimeError(
        "🚨 生产环境必须配置 JWT_SECRET_KEY 环境变量！请在 .env 或系统环境中设置。"
    )

# ==================== 密码哈希 ====================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ==================== OAuth2 ====================

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# ==================== 速率限制（内存缓存）====================

_login_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 300  # 5分钟
_RATE_LIMIT_MAX_ATTEMPTS = 5  # 最多 5 次失败尝试

def _check_rate_limit(identifier: str) -> bool:
    """检查是否超出速率限制（返回 True = 允许，False = 超限）"""
    now = time.time()
    attempts = _login_attempts[identifier]
    # 清理过期记录
    attempts[:] = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW]
    if len(attempts) >= _RATE_LIMIT_MAX_ATTEMPTS:
        return False
    return True

def _record_failed_attempt(identifier: str):
    """记录失败尝试"""
    _login_attempts[identifier].append(time.time())


# ==================== 工具函数 ====================

def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    校验密码强度（开源项目标准）
    返回 (是否合格, 错误提示)
    """
    if len(password) < 8:
        return False, "密码至少 8 个字符"
    if not re.search(r'[a-z]', password):
        return False, "密码必须包含小写字母"
    if not re.search(r'[A-Z]', password):
        return False, "密码必须包含大写字母"
    if not re.search(r'[0-9]', password):
        return False, "密码必须包含数字"
    # 可选：特殊字符要求（暂不强制，避免用户体验太差）
    # if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
    #     return False, "密码必须包含特殊字符"
    return True, ""


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """生成 JWT Token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ==================== 用户 CRUD ====================

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """按用户名查询用户"""
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, username: str, password: str) -> User:
    """创建新用户（密码哈希存储）"""
    user = User(
        username=username,
        hashed_password=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str, client_ip: str = "unknown") -> Optional[User]:
    """
    验证用户名和密码，返回用户对象或 None
    增加速率限制防暴力破解
    """
    # 速率限制（按 IP + 用户名）
    rate_key = f"{client_ip}:{username}"
    if not _check_rate_limit(rate_key):
        logger.warning(f"登录速率限制触发: {rate_key}")
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请 5 分钟后再试"
        )
    
    user = get_user_by_username(db, username)
    if not user:
        _record_failed_attempt(rate_key)
        return None
    if not verify_password(password, user.hashed_password):
        _record_failed_attempt(rate_key)
        return None
    return user


# ==================== FastAPI 依赖注入 ====================

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    从 JWT Token 中解析当前用户 —— 用作 Depends() 注入。
    所有需要鉴权的路由都应依赖此函数。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = get_user_by_username(db, username)
    if user is None:
        raise credentials_exception
    return user
