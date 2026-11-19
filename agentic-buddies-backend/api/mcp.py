import json
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text, table, column, update as sql_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel

from sql.sql_connect import get_db

router = APIRouter()

# ---------- SQLAlchemy Core 表定义 ----------
mcp_table = table(
    "mcp",
    column("id"),
    column("name"),
    column("type"),
    column("url"),
    column("headers", JSONB),
    column("timeout"),
)

# ---------- Pydantic 模型 ----------
class MCPCreate(BaseModel):
    name: str
    type: str  # 'sse' 或 'streamable-http'
    url: str
    headers: Optional[dict] = {}
    timeout: Optional[int] = 60

class MCPUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[dict] = None
    timeout: Optional[int] = None

class MCPResponse(BaseModel):
    id: int
    name: str
    type: str
    url: str
    headers: dict
    timeout: int

class NPCReference(BaseModel):
    id: int
    name: str
    character_prompt: Optional[str]
    related_world: Optional[int]

# ---------- 辅助函数 ----------
async def check_mcp_exist(db: AsyncSession, mcp_id: int) -> dict:
    result = await db.execute(
        text("SELECT id, name, type, url, headers, timeout FROM mcp WHERE id = :id"),
        {"id": mcp_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="MCP 服务不存在")
    return {
        "id": row.id,
        "name": row.name,
        "type": row.type,
        "url": row.url,
        "headers": row.headers,
        "timeout": row.timeout,
    }

async def check_mcp_in_use(db: AsyncSession, mcp_id: int) -> bool:
    result = await db.execute(
        text("SELECT 1 FROM npc_mcp_relations WHERE mcp_id = :mcp_id LIMIT 1"),
        {"mcp_id": mcp_id}
    )
    return result.fetchone() is not None

# ---------- 1. 列表 ----------
@router.get("/", response_model=List[MCPResponse])
async def list_mcp(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, name, type, url, headers, timeout FROM mcp ORDER BY id")
    )
    return [dict(row._mapping) for row in result.fetchall()]

# ---------- 2. 创建 ----------
@router.post("/", response_model=MCPResponse, status_code=201)
async def create_mcp(mcp: MCPCreate, db: AsyncSession = Depends(get_db)):
    check = await db.execute(
        text("SELECT id FROM mcp WHERE name = :name"),
        {"name": mcp.name}
    )
    if check.fetchone():
        raise HTTPException(status_code=400, detail="MCP 名称已被占用")

    if mcp.type not in ("sse", "streamable-http"):
        raise HTTPException(status_code=400, detail="type 必须是 'sse' 或 'streamable-http'")

    result = await db.execute(
        text("""
            INSERT INTO mcp (name, type, url, headers, timeout)
            VALUES (:name, :type, :url, :headers, :timeout)
            RETURNING id, name, type, url, headers, timeout
        """),
        {
            "name": mcp.name,
            "type": mcp.type,
            "url": mcp.url,
            "headers": json.dumps(mcp.headers or {}),
            "timeout": mcp.timeout or 30,
        }
    )
    row = result.fetchone()
    await db.commit()
    return dict(row._mapping)

# ---------- 3. 详情 ----------
@router.get("/{mcp_id}", response_model=MCPResponse)
async def get_mcp(mcp_id: int, db: AsyncSession = Depends(get_db)):
    return await check_mcp_exist(db, mcp_id)

# ---------- 4. 更新 ----------
@router.put("/{mcp_id}", response_model=MCPResponse)
async def update_mcp(
    mcp_id: int,
    update: MCPUpdate,
    db: AsyncSession = Depends(get_db)
):
    await check_mcp_exist(db, mcp_id)

    update_values = {}

    if update.name is not None:
        check = await db.execute(
            text("SELECT id FROM mcp WHERE name = :name AND id != :id"),
            {"name": update.name, "id": mcp_id}
        )
        if check.fetchone():
            raise HTTPException(status_code=400, detail="MCP 名称已被其他记录占用")
        update_values["name"] = update.name

    if update.type is not None:
        if update.type not in ("sse", "streamable-http"):
            raise HTTPException(status_code=400, detail="type 必须是 'sse' 或 'streamable-http'")
        update_values["type"] = update.type

    if update.url is not None:
        update_values["url"] = update.url

    if update.headers is not None:
        update_values["headers"] = update.headers

    if update.timeout is not None:
        update_values["timeout"] = update.timeout

    if not update_values:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    stmt = (
        sql_update(mcp_table)
        .where(mcp_table.c.id == mcp_id)
        .values(**update_values)
        .returning(
            mcp_table.c.id, mcp_table.c.name, mcp_table.c.type,
            mcp_table.c.url, mcp_table.c.headers, mcp_table.c.timeout,
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    return dict(result.fetchone()._mapping)

# ---------- 5. 删除 ----------
@router.delete("/{mcp_id}", status_code=204)
async def delete_mcp(mcp_id: int, db: AsyncSession = Depends(get_db)):
    await check_mcp_exist(db, mcp_id)

    if await check_mcp_in_use(db, mcp_id):
        raise HTTPException(
            status_code=400,
            detail="该 MCP 正被至少一个 NPC 使用，请先解除关联"
        )

    await db.execute(text("DELETE FROM mcp WHERE id = :id"), {"id": mcp_id})
    await db.commit()

# ---------- 6. 获取使用该 MCP 的 NPC 列表 ----------
@router.get("/{mcp_id}/npcs", response_model=List[NPCReference])
async def get_mcp_npcs(mcp_id: int, db: AsyncSession = Depends(get_db)):
    await check_mcp_exist(db, mcp_id)

    result = await db.execute(
        text("""
            SELECT n.id, n.name, n.character_prompt, n.related_world
            FROM npcs n
            JOIN npc_mcp_relations r ON n.id = r.npc_id
            WHERE r.mcp_id = :mcp_id
            ORDER BY n.id
        """),
        {"mcp_id": mcp_id}
    )
    return [dict(row._mapping) for row in result.fetchall()]
