"""认证路由"""
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, TokenResponse, CreateUserRequest
from app.utils.security import hash_password, verify_password, create_access_token, get_current_user, require_admin

router = APIRouter()

# 简易登录频率限制（内存级，5次失败后锁定 5 分钟）
_login_attempts = defaultdict(list)
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCK_SECONDS = 300


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    username = body.username
    now = time.time()

    # 清理过期的失败记录
    _login_attempts[username] = [t for t in _login_attempts[username] if now - t < _LOGIN_LOCK_SECONDS]

    # 检查是否被锁定
    if len(_login_attempts[username]) >= _LOGIN_MAX_ATTEMPTS:
        remaining = int(_LOGIN_LOCK_SECONDS - (now - _login_attempts[username][0]))
        raise HTTPException(status_code=429, detail=f"登录失败次数过多，请 {remaining} 秒后重试")

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(body.password, user.password_hash):
        _login_attempts[username].append(now)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 登录成功，清除失败记录
    _login_attempts.pop(username, None)

    token = create_access_token(user.username, user.role)
    return TokenResponse(
        access_token=token,
        username=user.username,
        role=user.role,
    )


@router.post("/register", response_model=TokenResponse)
async def register(
    body: CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员创建用户（需 admin 权限）

    普通用户无法创建新账户，防止权限提升。
    只有 admin 可以指定 role，非 admin 创建的用户默认为 reviewer。
    """
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 非 admin 用户只能创建 reviewer（双重保险）
    role = body.role if current_user.role == "admin" else "reviewer"

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.username, user.role)
    return TokenResponse(
        access_token=token,
        username=user.username,
        role=user.role,
    )
