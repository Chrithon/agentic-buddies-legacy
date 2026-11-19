import json
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text, table, column, update as sql_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel

from sql.sql_connect import get_db

router = APIRouter()

# SQLAlchemy Core 表定义
worlds_table = table(
    "worlds",
    column("id"),
    column("name"),
    column("description"),
    column("world_prompt"),
    column("kb_api_url"),
    column("kb_api_headers", JSONB),
    column("kb_api_timeout"),
    column("kb_api_data", JSONB),
)

# ---------- Pydantic 模型 ----------
class WorldCreate(BaseModel):
    name: str
    description: Optional[str] = None
    world_prompt: str
    kb_api_url: Optional[str] = None
    kb_api_headers: Optional[dict] = {}
    kb_api_timeout: Optional[int] = 30
    kb_api_data: Optional[dict] = {}  # 知识库 API 请求数据（如 Dify dataset_id/retrieval_model）

class WorldUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    world_prompt: Optional[str] = None
    kb_api_url: Optional[str] = None
    kb_api_headers: Optional[dict] = None
    kb_api_timeout: Optional[int] = None
    kb_api_data: Optional[dict] = None

class WorldResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    world_prompt: str
    kb_api_url: Optional[str]
    kb_api_headers: Optional[dict]
    kb_api_timeout: Optional[int]
    kb_api_data: Optional[dict]

# ---------- 辅助函数 ----------
async def check_world_exist(db: AsyncSession, world_id: int) -> dict:
    result = await db.execute(
        text("SELECT id, name, description, world_prompt, kb_api_url, kb_api_headers, kb_api_timeout, kb_api_data FROM worlds WHERE id = :id"),
        {"id": world_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="世界观不存在")
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "world_prompt": row.world_prompt,
        "kb_api_url": row.kb_api_url,
        "kb_api_headers": row.kb_api_headers,
        "kb_api_timeout": row.kb_api_timeout,
        "kb_api_data": row.kb_api_data,
    }

async def check_world_in_use(db: AsyncSession, world_id: int) -> bool:
    result = await db.execute(
        text("SELECT id FROM npcs WHERE related_world = :world_id LIMIT 1"),
        {"world_id": world_id}
    )
    return result.fetchone() is not None

# ---------- 1. 列表 ----------
@router.get("/", response_model=List[WorldResponse])
async def list_worlds(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, name, description, world_prompt, kb_api_url, kb_api_headers, kb_api_timeout, kb_api_data FROM worlds ORDER BY id")
    )
    return [dict(row._mapping) for row in result.fetchall()]

# ---------- 2. 创建 ----------
@router.post("/", response_model=WorldResponse, status_code=201)
async def create_world(world: WorldCreate, db: AsyncSession = Depends(get_db)):
    check = await db.execute(
        text("SELECT id FROM worlds WHERE name = :name"),
        {"name": world.name}
    )
    if check.fetchone():
        raise HTTPException(status_code=400, detail="世界观名称已被占用")

    result = await db.execute(
        text("""
            INSERT INTO worlds (name, description, world_prompt, kb_api_url, kb_api_headers, kb_api_timeout, kb_api_data)
            VALUES (:name, :description, :world_prompt, :kb_api_url, :kb_api_headers, :kb_api_timeout, :kb_api_data)
            RETURNING id, name, description, world_prompt, kb_api_url, kb_api_headers, kb_api_timeout, kb_api_data
        """),
        {
            "name": world.name,
            "description": world.description,
            "world_prompt": world.world_prompt,
            "kb_api_url": world.kb_api_url,
            "kb_api_headers": json.dumps(world.kb_api_headers or {}),
            "kb_api_timeout": world.kb_api_timeout,
            "kb_api_data": json.dumps(world.kb_api_data or {}),
        }
    )
    row = result.fetchone()
    await db.commit()
    return dict(row._mapping)

# ---------- 3. 详情 ----------
@router.get("/{world_id}", response_model=WorldResponse)
async def get_world(world_id: int, db: AsyncSession = Depends(get_db)):
    return await check_world_exist(db, world_id)

# ---------- 4. 更新 ----------
@router.put("/{world_id}", response_model=WorldResponse)
async def update_world(
    world_id: int,
    update: WorldUpdate,
    db: AsyncSession = Depends(get_db)
):
    await check_world_exist(db, world_id)

    update_values = {}
    sent_fields = update.model_dump(exclude_unset=True)

    if "name" in sent_fields:
        name_val = sent_fields["name"]
        if name_val is not None:
            check = await db.execute(
                text("SELECT id FROM worlds WHERE name = :name AND id != :id"),
                {"name": name_val, "id": world_id}
            )
            if check.fetchone():
                raise HTTPException(status_code=400, detail="世界观名称已被其他记录占用")
            update_values["name"] = name_val

    if "description" in sent_fields:
        update_values["description"] = sent_fields["description"]

    if "world_prompt" in sent_fields:
        update_values["world_prompt"] = sent_fields["world_prompt"]

    if "kb_api_url" in sent_fields:
        update_values["kb_api_url"] = sent_fields["kb_api_url"]

    if "kb_api_headers" in sent_fields:
        update_values["kb_api_headers"] = sent_fields["kb_api_headers"]

    if "kb_api_timeout" in sent_fields:
        update_values["kb_api_timeout"] = sent_fields["kb_api_timeout"]

    if "kb_api_data" in sent_fields:
        update_values["kb_api_data"] = sent_fields["kb_api_data"]

    if not update_values:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    stmt = (
        sql_update(worlds_table)
        .where(worlds_table.c.id == world_id)
        .values(**update_values)
        .returning(
            worlds_table.c.id, worlds_table.c.name,
            worlds_table.c.description, worlds_table.c.world_prompt,
            worlds_table.c.kb_api_url, worlds_table.c.kb_api_headers,
            worlds_table.c.kb_api_timeout, worlds_table.c.kb_api_data,
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    return dict(result.fetchone()._mapping)

# ---------- 5. 删除 ----------
@router.delete("/{world_id}", status_code=204)
async def delete_world(world_id: int, db: AsyncSession = Depends(get_db)):
    await check_world_exist(db, world_id)

    if await check_world_in_use(db, world_id):
        raise HTTPException(
            status_code=400,
            detail="该世界观正被至少一个 NPC 使用，请先解除关联或删除对应 NPC"
        )

    await db.execute(text("DELETE FROM worlds WHERE id = :id"), {"id": world_id})
    await db.commit()
