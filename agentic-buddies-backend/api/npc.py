import json
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import text, table, column, update as sql_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel, Field

from sql.sql_connect import get_db

router = APIRouter()

# SQLAlchemy Core 表定义（用于安全的 UPDATE 表达式，避免 f-string 拼接 SQL）
npcs_table = table(
    "npcs",
    column("id"),
    column("name"),
    column("model_config", JSONB),
    column("character_prompt"),
    column("related_world"),
    column("is_enabled"),
    column("owner"),
)

# ---------- Pydantic 模型 ----------
class NPCCreate(BaseModel):
    name: str
    config: dict = Field(alias="model_config")
    character_prompt: str  # 必填：角色设定 Prompt
    related_world: int  # 必填：NPC 必须属于某个世界观
    is_enabled: bool = True  # 默认启用
    owner: int  # 外键 users.id

class NPCUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = Field(default=None, alias="model_config")
    character_prompt: Optional[str] = None  # 部分更新；若提供则不能为 null/空
    related_world: Optional[int] = None  # 部分更新；若提供则不能为 null
    is_enabled: Optional[bool] = None  # 部分更新；启用/禁用状态
    owner: Optional[int] = None

class NPCResponse(BaseModel):
    id: int
    name: str
    config: dict = Field(alias="model_config")
    character_prompt: str
    related_world: int
    is_enabled: bool
    owner: int

# ---------- 辅助函数 ----------
async def check_npc_exist(db: AsyncSession, npc_id: int) -> dict:
    """根据 ID 获取 NPC，不存在则抛出 404"""
    result = await db.execute(
        text("SELECT id, name, model_config, character_prompt, related_world, is_enabled, owner FROM npcs WHERE id = :id"),
        {"id": npc_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="NPC 不存在")
    return {
        "id": row.id,
        "name": row.name,
        "model_config": row.model_config,
        "character_prompt": row.character_prompt,
        "related_world": row.related_world,
        "is_enabled": row.is_enabled,
        "owner": row.owner,
    }

# ---------- 1. 列表（支持筛选） ----------
@router.get("/", response_model=List[NPCResponse])
async def list_npcs(
    related_world: Optional[int] = Query(None, description="按世界观 ID 筛选"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取 NPC 列表，可按 related_world 筛选。
    """
    query = "SELECT id, name, model_config, character_prompt, related_world, is_enabled, owner FROM npcs WHERE 1=1"
    params = {}
    if related_world is not None:
        query += " AND related_world = :related_world"
        params["related_world"] = related_world

    result = await db.execute(text(query), params)
    rows = result.fetchall()
    return [
        {
            "id": row.id,
            "name": row.name,
            "model_config": row.model_config,
            "character_prompt": row.character_prompt,
            "related_world": row.related_world,
            "is_enabled": row.is_enabled,
            "owner": row.owner,
        }
        for row in rows
    ]

# ---------- 2. 创建 ----------
@router.post("/", response_model=NPCResponse, status_code=201)
async def create_npc(npc: NPCCreate, db: AsyncSession = Depends(get_db)):
    """
    创建新 NPC。
    related_world 为必填，必须指向存在的世界观；owner 必须指向已存在的用户。
    """
    # 检查 related_world 是否存在（必填，Pydantic 已保证非空）
    world_check = await db.execute(
        text("SELECT id FROM worlds WHERE id = :id"),
        {"id": npc.related_world}
    )
    if not world_check.fetchone():
        raise HTTPException(status_code=400, detail="关联的世界观不存在")

    # 检查 owner 用户是否存在
    owner_check = await db.execute(
        text("SELECT id FROM users WHERE id = :id"),
        {"id": npc.owner}
    )
    if not owner_check.fetchone():
        raise HTTPException(status_code=400, detail="owner 对应的用户不存在")

    # 插入 NPC
    result = await db.execute(
        text("""
            INSERT INTO npcs (name, model_config, character_prompt, related_world, is_enabled, owner)
            VALUES (:name, :model_config, :character_prompt, :related_world, :is_enabled, :owner)
            RETURNING id, name, model_config, character_prompt, related_world, is_enabled, owner
        """),
        {
            "name": npc.name,
            "model_config": json.dumps(npc.config),
            "character_prompt": npc.character_prompt,
            "related_world": npc.related_world,
            "is_enabled": npc.is_enabled,
            "owner": npc.owner,
        }
    )
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "name": row.name,
        "model_config": row.model_config,
        "character_prompt": row.character_prompt,
        "related_world": row.related_world,
        "is_enabled": row.is_enabled,
        "owner": row.owner,
    }

# ---------- 3. 详情 ----------
@router.get("/{npc_id}", response_model=NPCResponse)
async def get_npc(npc_id: int, db: AsyncSession = Depends(get_db)):
    """
    获取单个 NPC 详情。
    """
    return await check_npc_exist(db, npc_id)

# ---------- 4. 更新 ----------
@router.put("/{npc_id}", response_model=NPCResponse)
async def update_npc(
    npc_id: int,
    update: NPCUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    部分更新 NPC 信息。仅提供需要修改的字段即可。
    """
    # 先检查是否存在
    await check_npc_exist(db, npc_id)

    # 收集需要更新的字段（SQLAlchemy Core 自动参数绑定，杜绝 SQL 注入）
    # exclude_unset 区分"未传"与"显式传 null"
    update_values = {}
    sent_fields = update.model_dump(exclude_unset=True)

    if "name" in sent_fields:
        update_values["name"] = sent_fields["name"]

    if "config" in sent_fields:
        update_values["model_config"] = sent_fields["config"]

    if "character_prompt" in sent_fields:
        # 角色 Prompt 必填，不允许置空
        if not sent_fields["character_prompt"]:
            raise HTTPException(status_code=400, detail="角色 Prompt 不能为空")
        update_values["character_prompt"] = sent_fields["character_prompt"]

    if "related_world" in sent_fields:
        # 世界观必填，不允许置空（解绑操作已被取消）
        if sent_fields["related_world"] is None:
            raise HTTPException(status_code=400, detail="NPC 必须关联一个世界观，不能解绑")
        world_check = await db.execute(
            text("SELECT id FROM worlds WHERE id = :id"),
            {"id": sent_fields["related_world"]}
        )
        if not world_check.fetchone():
            raise HTTPException(status_code=400, detail="关联的世界观不存在")
        update_values["related_world"] = sent_fields["related_world"]

    if "owner" in sent_fields:
        if sent_fields["owner"] is not None:
            owner_check = await db.execute(
                text("SELECT id FROM users WHERE id = :id"),
                {"id": sent_fields["owner"]}
            )
            if not owner_check.fetchone():
                raise HTTPException(status_code=400, detail="owner 对应的用户不存在")
            update_values["owner"] = sent_fields["owner"]

    if "is_enabled" in sent_fields:
        update_values["is_enabled"] = sent_fields["is_enabled"]

    if not update_values:
        raise HTTPException(status_code=400, detail="没有提供任何需要更新的字段")

    stmt = (
        sql_update(npcs_table)
        .where(npcs_table.c.id == npc_id)
        .values(**update_values)
        .returning(
            npcs_table.c.id,
            npcs_table.c.name,
            npcs_table.c.model_config,
            npcs_table.c.character_prompt,
            npcs_table.c.related_world,
            npcs_table.c.is_enabled,
            npcs_table.c.owner,
        )
    )
    result = await db.execute(stmt)
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "name": row.name,
        "model_config": row.model_config,
        "character_prompt": row.character_prompt,
        "related_world": row.related_world,
        "is_enabled": row.is_enabled,
        "owner": row.owner,
    }

# ---------- 5. 删除 ----------
@router.delete("/{npc_id}", status_code=204)
async def delete_npc(npc_id: int, db: AsyncSession = Depends(get_db)):
    """
    删除 NPC，同时级联删除关联的 npc_mcp_relations 和 conversation_logs。
    """
    result = await db.execute(
        text("DELETE FROM npcs WHERE id = :id RETURNING id"),
        {"id": npc_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="NPC 不存在")
    await db.commit()
    # 返回 204 No Content

# ---------- MCP 关联管理 ----------
class MCPBindingRequest(BaseModel):
    mcp_id: int

class MCPResponse(BaseModel):
    id: int
    name: str
    type: str
    url: str
    headers: dict
    timeout: int

@router.post("/{npc_id}/mcp", status_code=201)
async def bind_mcp_to_npc(
    npc_id: int,
    request: MCPBindingRequest,
    db: AsyncSession = Depends(get_db)
):
    """将指定的 MCP 绑定到 NPC"""
    # 检查 NPC 是否存在
    await check_npc_exist(db, npc_id)

    # 检查 MCP 是否存在
    mcp_check = await db.execute(
        text("SELECT id FROM mcp WHERE id = :id"),
        {"id": request.mcp_id}
    )
    if not mcp_check.fetchone():
        raise HTTPException(status_code=404, detail="MCP 服务不存在")

    # 检查是否已经绑定
    exist_check = await db.execute(
        text("SELECT 1 FROM npc_mcp_relations WHERE npc_id = :npc_id AND mcp_id = :mcp_id"),
        {"npc_id": npc_id, "mcp_id": request.mcp_id}
    )
    if exist_check.fetchone():
        raise HTTPException(status_code=400, detail="该 MCP 已绑定此 NPC")

    await db.execute(
        text("INSERT INTO npc_mcp_relations (npc_id, mcp_id) VALUES (:npc_id, :mcp_id)"),
        {"npc_id": npc_id, "mcp_id": request.mcp_id}
    )
    await db.commit()
    return {"message": "MCP 绑定成功"}

@router.delete("/{npc_id}/mcp/{mcp_id}", status_code=204)
async def unbind_mcp_from_npc(
    npc_id: int,
    mcp_id: int,
    db: AsyncSession = Depends(get_db)
):
    """从 NPC 解绑指定的 MCP"""
    # 检查 NPC 是否存在
    await check_npc_exist(db, npc_id)

    result = await db.execute(
        text("DELETE FROM npc_mcp_relations WHERE npc_id = :npc_id AND mcp_id = :mcp_id RETURNING 1"),
        {"npc_id": npc_id, "mcp_id": mcp_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="该 NPC 未绑定此 MCP")
    await db.commit()
    # 204 No Content

@router.get("/{npc_id}/mcp", response_model=List[MCPResponse])
async def get_npc_mcp_bindings(
    npc_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取某个 NPC 绑定的所有 MCP 服务详情"""
    # 检查 NPC 是否存在
    await check_npc_exist(db, npc_id)

    result = await db.execute(
        text("""
            SELECT m.id, m.name, m.type, m.url, m.headers, m.timeout
            FROM mcp m
            JOIN npc_mcp_relations r ON m.id = r.mcp_id
            WHERE r.npc_id = :npc_id
            ORDER BY m.id
        """),
        {"npc_id": npc_id}
    )
    rows = result.fetchall()
    return [
        {
            "id": row.id,
            "name": row.name,
            "type": row.type,
            "url": row.url,
            "headers": row.headers,
            "timeout": row.timeout,
        }
        for row in rows
    ]

# ---------- 行为树关联管理 ----------
class BehaviorTreeBindingRequest(BaseModel):
    behavior_tree_id: int

class BehaviorTreeBriefResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]

@router.post("/{npc_id}/behavior-trees", status_code=201)
async def bind_behavior_tree_to_npc(
    npc_id: int,
    request: BehaviorTreeBindingRequest,
    db: AsyncSession = Depends(get_db)
):
    """将指定的行为树绑定到 NPC"""
    await check_npc_exist(db, npc_id)

    tree_check = await db.execute(
        text("SELECT id FROM behavior_tree WHERE id = :id"),
        {"id": request.behavior_tree_id}
    )
    if not tree_check.fetchone():
        raise HTTPException(status_code=404, detail="行为树不存在")

    exist_check = await db.execute(
        text("""
            SELECT 1 FROM npc_behavior_relations
            WHERE npc_id = :npc_id AND behavior_tree_id = :behavior_tree_id
        """),
        {"npc_id": npc_id, "behavior_tree_id": request.behavior_tree_id}
    )
    if exist_check.fetchone():
        raise HTTPException(status_code=400, detail="该行为树已绑定此 NPC")

    await db.execute(
        text("""
            INSERT INTO npc_behavior_relations (npc_id, behavior_tree_id)
            VALUES (:npc_id, :behavior_tree_id)
        """),
        {"npc_id": npc_id, "behavior_tree_id": request.behavior_tree_id}
    )
    await db.commit()
    return {"message": "行为树绑定成功"}

@router.delete("/{npc_id}/behavior-trees/{tree_id}", status_code=204)
async def unbind_behavior_tree_from_npc(
    npc_id: int,
    tree_id: int,
    db: AsyncSession = Depends(get_db)
):
    """从 NPC 解绑指定的行为树"""
    await check_npc_exist(db, npc_id)

    result = await db.execute(
        text("""
            DELETE FROM npc_behavior_relations
            WHERE npc_id = :npc_id AND behavior_tree_id = :tree_id
            RETURNING 1
        """),
        {"npc_id": npc_id, "tree_id": tree_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="该 NPC 未绑定此行为树")
    await db.commit()
    # 204 No Content

@router.get("/{npc_id}/behavior-trees", response_model=List[BehaviorTreeBriefResponse])
async def get_npc_behavior_tree_bindings(
    npc_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取某个 NPC 绑定的所有行为树"""
    await check_npc_exist(db, npc_id)

    result = await db.execute(
        text("""
            SELECT bt.id, bt.name, bt.description
            FROM behavior_tree bt
            JOIN npc_behavior_relations r ON bt.id = r.behavior_tree_id
            WHERE r.npc_id = :npc_id
            ORDER BY bt.id
        """),
        {"npc_id": npc_id}
    )
    return [dict(row._mapping) for row in result.fetchall()]
