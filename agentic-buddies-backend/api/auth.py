import os
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy import text, table, column, update as sql_update, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel, Field

from sql.sql_connect import get_db

router = APIRouter()

# SQLAlchemy Core 表定义（UPDATE 使用表达式，避免字符串拼接 SQL）
users_table = table(
    "users",
    column("id"),
    column("username"),
    column("password_hash"),
    column("is_enabled"),
    column("is_admin"),
    column("attmpts"),
    column("last_failed_attempt"),
)

# ---------- 配置 ----------
# JWT 密钥必须从环境变量读取；未配置时生成临时随机密钥（重启后旧 token 失效）
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    print("警告: 未配置 SECRET_KEY 环境变量，已生成临时密钥，服务重启后所有 token 将失效")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 小时

# ---------- 防爆破：数据库持久化计数 + 定时锁定 ----------
# 连续失败 MAX_FAILED_ATTEMPTS 次后，账户锁定 LOCKOUT_DURATION
# 锁定起点为 users.last_failed_attempt，到期后自动解除
# is_enabled 仅由管理员控制，防爆破逻辑不再修改该字段
MAX_FAILED_ATTEMPTS = 3
LOCKOUT_DURATION = timedelta(hours=1)

# ---------- Pydantic 模型 ----------
class LoginRequest(BaseModel):
    username: str
    password: str

class UserInfo(BaseModel):
    id: int
    username: str
    is_enabled: bool
    is_admin: bool

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo

# ---------- 辅助函数 ----------
def password_bytes(password: str) -> bytes:
    """bcrypt 上限 72 字节，统一截断处理"""
    return password.encode("utf-8")[:72]

def verify_password(plain: str, password_hash: str) -> bool:
    """同步 bcrypt 校验（在线程中调用，避免阻塞事件循环）"""
    try:
        return bcrypt.checkpw(password_bytes(plain), password_hash.encode("utf-8"))
    except ValueError:
        return False

def create_access_token(user_id: int, username: str, is_admin: bool) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def locked_remaining(attmpts: int, last_failed_attempt: Optional[datetime]) -> Optional[timedelta]:
    """若账户处于锁定期内，返回剩余锁定时长；否则返回 None。

    锁定条件：失败次数达到阈值，且距 last_failed_attempt 不足 LOCKOUT_DURATION。
    """
    if attmpts >= MAX_FAILED_ATTEMPTS and last_failed_attempt is not None:
        elapsed = datetime.now(timezone.utc) - last_failed_attempt
        remaining = LOCKOUT_DURATION - elapsed
        if remaining.total_seconds() > 0:
            return remaining
    return None

async def record_failure(db: AsyncSession, user_id: int, current_attmpts: int) -> int:
    """记录一次登录失败：attmpts+1、刷新 last_failed_attempt。

    返回累计失败次数。SQLAlchemy Core 自动参数绑定，杜绝 SQL 注入。
    """
    new_attmpts = current_attmpts + 1
    stmt = (
        sql_update(users_table)
        .where(users_table.c.id == user_id)
        .values(attmpts=new_attmpts, last_failed_attempt=func.now())
    )
    await db.execute(stmt)
    await db.commit()
    return new_attmpts

async def reset_failures(db: AsyncSession, user_id: int) -> None:
    """登录成功：清零失败计数并清空锁定时间"""
    stmt = (
        sql_update(users_table)
        .where(users_table.c.id == user_id)
        .values(attmpts=0, last_failed_attempt=None)
    )
    await db.execute(stmt)
    await db.commit()

# ---------- 登录（不提供注册接口） ----------
@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    用户登录。
    - 用户不存在与密码错误返回相同的通用提示，防止用户名枚举
    - 连续失败 3 次后账户锁定 1 小时（从 last_failed_attempt 起算，到期自动解除）
    - 距上次失败超过 1 小时后，失败计数重新从 0 累计（时间窗口机制）
    """
    # 参数化查询，杜绝 SQL 注入
    result = await db.execute(
        text("""
            SELECT id, username, password_hash, is_enabled, is_admin, attmpts, last_failed_attempt
            FROM users
            WHERE username = :username
        """),
        {"username": request.username}
    )
    row = result.fetchone()

    if not row:
        # 与密码错误使用相同提示，防止用户名枚举
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    if not row.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用，请联系管理员"
        )

    # 检查是否处于锁定期（1 小时）
    remaining = locked_remaining(row.attmpts, row.last_failed_attempt)
    if remaining is not None:
        minutes = int(remaining.total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"失败次数过多，账户已锁定，请在 {minutes} 分钟后重试"
        )

    # 不在锁定期内，且距上次失败已超过 LOCKOUT_DURATION：
    # 清零历史失败计数，让"连续失败"只在时间窗口内累计。
    # 否则锁定到期后 attmpts 仍 >= 阈值，再错一次会立即重新锁定（滚动锁定）。
    current_attmpts = row.attmpts
    if (
        current_attmpts > 0
        and row.last_failed_attempt is not None
        and datetime.now(timezone.utc) - row.last_failed_attempt >= LOCKOUT_DURATION
    ):
        await reset_failures(db, row.id)
        current_attmpts = 0

    # bcrypt 为 CPU 密集型同步操作，放入线程避免阻塞事件循环
    password_ok = await asyncio.to_thread(verify_password, request.password, row.password_hash)

    if not password_ok:
        count = await record_failure(db, row.id, current_attmpts)
        if count >= MAX_FAILED_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="失败次数过多，账户已锁定 1 小时"
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    # 登录成功，清零失败计数
    await reset_failures(db, row.id)

    token = create_access_token(row.id, row.username, row.is_admin)
    return TokenResponse(
        access_token=token,
        user=UserInfo(
            id=row.id,
            username=row.username,
            is_enabled=row.is_enabled,
            is_admin=row.is_admin,
        )
    )

# ---------- Token 解析依赖（预留，后续接口鉴权使用） ----------
bearer_scheme = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db)
) -> UserInfo:
    """解析 Bearer Token 并返回当前用户（预留依赖）"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据"
        )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", "0"))
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的 token"
        )

    result = await db.execute(
        text("SELECT id, username, is_enabled, is_admin FROM users WHERE id = :id"),
        {"id": user_id}
    )
    row = result.fetchone()
    if not row or not row.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账户不存在或已被禁用"
        )
    return UserInfo(
        id=row.id,
        username=row.username,
        is_enabled=row.is_enabled,
        is_admin=row.is_admin,
    )

async def require_admin(current_user: UserInfo = Depends(get_current_user)) -> UserInfo:
    """要求管理员权限（预留依赖，后续管理接口使用）"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    return current_user

# ---------- 当前用户信息 ----------
@router.get("/me", response_model=UserInfo)
async def get_me(current_user: UserInfo = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return current_user

# ---------- 本人修改密码 ----------
class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=72)
    confirm_password: str

@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChange,
    current_user: UserInfo = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """用户本人修改密码。

    - 必须提供正确的旧密码
    - 两次输入的新密码必须一致，否则拒绝修改
    - 成功后清零登录失败计数
    注意：已签发的 JWT 在过期前仍然有效（无吊销机制）。
    """
    if body.new_password != body.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="两次输入的新密码不一致"
        )
    if body.new_password == body.old_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与旧密码相同"
        )

    result = await db.execute(
        text("SELECT password_hash FROM users WHERE id = :id"),
        {"id": current_user.id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="账户不存在"
        )

    # bcrypt 为 CPU 密集型同步操作，放入线程避免阻塞事件循环
    old_ok = await asyncio.to_thread(verify_password, body.old_password, row.password_hash)
    if not old_ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误"
        )

    new_hash = await asyncio.to_thread(
        lambda: bcrypt.hashpw(password_bytes(body.new_password), bcrypt.gensalt()).decode()
    )
    stmt = (
        sql_update(users_table)
        .where(users_table.c.id == current_user.id)
        .values(password_hash=new_hash, attmpts=0, last_failed_attempt=None)
    )
    await db.execute(stmt)
    await db.commit()
    # 204 No Content
