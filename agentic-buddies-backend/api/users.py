import asyncio
from datetime import datetime
from typing import Optional, List

import bcrypt
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text, table, column, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from sql.sql_connect import get_db
from api.auth import require_admin, password_bytes, UserInfo
from config import get_default_reset_password

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

# ---------- Pydantic 模型 ----------
class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=8, max_length=72)
    is_admin: bool = False

class UserUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    is_admin: Optional[bool] = None

# 管理员重置密码时使用的默认密码从 conf.yaml 的 auth.default_reset_password 读取，
# 未配置时重置接口失败关闭，禁止回退到硬编码密码。

class UserResponse(BaseModel):
    id: int
    username: str
    is_enabled: bool
    is_admin: bool
    attmpts: int
    last_failed_attempt: Optional[datetime]

# ---------- 辅助函数 ----------
async def check_user_exist(db: AsyncSession, user_id: int) -> dict:
    """根据 ID 获取用户（不含密码哈希），不存在则 404"""
    result = await db.execute(
        text("""
            SELECT id, username, is_enabled, is_admin, attmpts, last_failed_attempt
            FROM users WHERE id = :id
        """),
        {"id": user_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "id": row.id,
        "username": row.username,
        "is_enabled": row.is_enabled,
        "is_admin": row.is_admin,
        "attmpts": row.attmpts,
        "last_failed_attempt": row.last_failed_attempt,
    }

def hash_password(password: str) -> str:
    """bcrypt 加密（在线程中调用，避免阻塞事件循环）"""
    return bcrypt.hashpw(password_bytes(password), bcrypt.gensalt()).decode()

# ---------- 1. 用户列表 ----------
@router.get("/", response_model=List[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: UserInfo = Depends(require_admin)
):
    """列出所有用户（不含密码哈希），仅管理员可用"""
    result = await db.execute(
        text("""
            SELECT id, username, is_enabled, is_admin, attmpts, last_failed_attempt
            FROM users ORDER BY id
        """)
    )
    return [
        {
            "id": row.id,
            "username": row.username,
            "is_enabled": row.is_enabled,
            "is_admin": row.is_admin,
            "attmpts": row.attmpts,
            "last_failed_attempt": row.last_failed_attempt,
        }
        for row in result.fetchall()
    ]

# ---------- 2. 创建用户 ----------
@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    user: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: UserInfo = Depends(require_admin)
):
    """创建新用户，仅管理员可用。系统不提供公开注册接口。"""
    check = await db.execute(
        text("SELECT id FROM users WHERE username = :username"),
        {"username": user.username}
    )
    if check.fetchone():
        raise HTTPException(status_code=400, detail="用户名已被占用")

    # bcrypt 为 CPU 密集型同步操作，放入线程避免阻塞事件循环
    password_hash = await asyncio.to_thread(hash_password, user.password)

    result = await db.execute(
        text("""
            INSERT INTO users (username, password_hash, is_enabled, is_admin, attmpts)
            VALUES (:username, :password_hash, true, :is_admin, 0)
            RETURNING id, username, is_enabled, is_admin, attmpts, last_failed_attempt
        """),
        {
            "username": user.username,
            "password_hash": password_hash,
            "is_admin": user.is_admin,
        }
    )
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "username": row.username,
        "is_enabled": row.is_enabled,
        "is_admin": row.is_admin,
        "attmpts": row.attmpts,
        "last_failed_attempt": row.last_failed_attempt,
    }

# ---------- 3. 更新状态（启用/禁用、角色） ----------
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    update: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(require_admin)
):
    """更新用户启用状态或角色，仅管理员可用。禁止修改自己的状态/角色。"""
    await check_user_exist(db, user_id)

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的状态或角色")

    update_values = {}
    if update.is_enabled is not None:
        update_values["is_enabled"] = update.is_enabled
    if update.is_admin is not None:
        update_values["is_admin"] = update.is_admin

    if not update_values:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    stmt = (
        sql_update(users_table)
        .where(users_table.c.id == user_id)
        .values(**update_values)
        .returning(
            users_table.c.id,
            users_table.c.username,
            users_table.c.is_enabled,
            users_table.c.is_admin,
            users_table.c.attmpts,
            users_table.c.last_failed_attempt,
        )
    )
    result = await db.execute(stmt)
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "username": row.username,
        "is_enabled": row.is_enabled,
        "is_admin": row.is_admin,
        "attmpts": row.attmpts,
        "last_failed_attempt": row.last_failed_attempt,
    }

# ---------- 4. 重置密码（conf.yaml 中配置的默认密码） ----------
@router.put("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserInfo = Depends(require_admin)
):
    """管理员将用户密码重置为 conf.yaml 中配置的默认密码。

    默认密码来自 ``auth.default_reset_password``（或环境变量
    ``DEFAULT_RESET_PASSWORD``）；未配置时返回 500，不会回退到硬编码值。
    同时清零失败计数并解除锁定，重置后应提醒用户尽快登录并自行修改密码。
    """
    default_password = get_default_reset_password()
    if not default_password:
        raise HTTPException(
            status_code=500,
            detail="未配置默认重置密码，请检查 conf.yaml 的 auth.default_reset_password",
        )

    await check_user_exist(db, user_id)

    password_hash = await asyncio.to_thread(hash_password, default_password)

    stmt = (
        sql_update(users_table)
        .where(users_table.c.id == user_id)
        .values(password_hash=password_hash, attmpts=0, last_failed_attempt=None)
    )
    await db.execute(stmt)
    await db.commit()
    # 204 No Content

# ---------- 5. 解锁账户 ----------
@router.post("/{user_id}/unlock", status_code=204)
async def unlock_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: UserInfo = Depends(require_admin)
):
    """清零登录失败计数，解除防爆破锁定"""
    await check_user_exist(db, user_id)

    stmt = (
        sql_update(users_table)
        .where(users_table.c.id == user_id)
        .values(attmpts=0, last_failed_attempt=None)
    )
    await db.execute(stmt)
    await db.commit()
    # 204 No Content

# ---------- 6. 删除用户 ----------
@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(require_admin)
):
    """删除用户，仅管理员可用。禁止删除自己。"""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账户")

    result = await db.execute(
        text("DELETE FROM users WHERE id = :id RETURNING id"),
        {"id": user_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="用户不存在")
    await db.commit()
    # 204 No Content
