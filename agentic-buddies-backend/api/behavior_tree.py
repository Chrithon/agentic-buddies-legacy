import json
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text, table, column, update as sql_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Any
from pydantic import BaseModel

from sql.sql_connect import get_db

router = APIRouter()

# SQLAlchemy Core 表定义（用于安全的 UPDATE 表达式，避免 f-string 拼接 SQL）
behavior_tree_table = table(
    "behavior_tree",
    column("id"),
    column("name"),
    column("description"),
    column("tree_definition", JSONB),
)

# ---------- Pydantic 模型 ----------
class BehaviorTreeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tree_definition: dict  # JSONB

class BehaviorTreeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tree_definition: Optional[dict] = None

class BehaviorTreeResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    tree_definition: dict

# ---------- 辅助函数 ----------
async def check_tree_exist(db: AsyncSession, tree_id: int) -> dict:
    result = await db.execute(
        text("SELECT id, name, description, tree_definition FROM behavior_tree WHERE id = :id"),
        {"id": tree_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="行为树不存在")
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "tree_definition": row.tree_definition,
    }

# ---------- 1. 列表 ----------
@router.get("/", response_model=List[BehaviorTreeResponse])
async def list_trees(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, name, description, tree_definition FROM behavior_tree ORDER BY id")
    )
    rows = result.fetchall()
    return [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "tree_definition": row.tree_definition,
        }
        for row in rows
    ]

# ---------- 2. 创建 ----------
@router.post("/", response_model=BehaviorTreeResponse, status_code=201)
async def create_tree(tree: BehaviorTreeCreate, db: AsyncSession = Depends(get_db)):
    # 检查 name 唯一性
    check = await db.execute(
        text("SELECT id FROM behavior_tree WHERE name = :name"),
        {"name": tree.name}
    )
    if check.fetchone():
        raise HTTPException(status_code=400, detail="行为树名称已被占用")

    result = await db.execute(
        text("""
            INSERT INTO behavior_tree (name, description, tree_definition)
            VALUES (:name, :description, :tree_definition)
            RETURNING id, name, description, tree_definition
        """),
        {
            "name": tree.name,
            "description": tree.description,
            "tree_definition": json.dumps(tree.tree_definition),
        }
    )
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "tree_definition": row.tree_definition,
    }

# ---------- 3. 详情 ----------
@router.get("/{tree_id}", response_model=BehaviorTreeResponse)
async def get_tree(tree_id: int, db: AsyncSession = Depends(get_db)):
    return await check_tree_exist(db, tree_id)

# ---------- 4. 更新 ----------
@router.put("/{tree_id}", response_model=BehaviorTreeResponse)
async def update_tree(
    tree_id: int,
    update: BehaviorTreeUpdate,
    db: AsyncSession = Depends(get_db)
):
    await check_tree_exist(db, tree_id)

    # 收集需要更新的字段（SQLAlchemy Core 自动参数绑定，杜绝 SQL 注入）
    update_values = {}

    if update.name is not None:
        check = await db.execute(
            text("SELECT id FROM behavior_tree WHERE name = :name AND id != :id"),
            {"name": update.name, "id": tree_id}
        )
        if check.fetchone():
            raise HTTPException(status_code=400, detail="行为树名称已被其他记录占用")
        update_values["name"] = update.name

    if update.description is not None:
        update_values["description"] = update.description

    if update.tree_definition is not None:
        update_values["tree_definition"] = update.tree_definition

    if not update_values:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    stmt = (
        sql_update(behavior_tree_table)
        .where(behavior_tree_table.c.id == tree_id)
        .values(**update_values)
        .returning(
            behavior_tree_table.c.id,
            behavior_tree_table.c.name,
            behavior_tree_table.c.description,
            behavior_tree_table.c.tree_definition,
        )
    )
    result = await db.execute(stmt)
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "tree_definition": row.tree_definition,
    }

# ---------- 5. 删除 ----------
@router.delete("/{tree_id}", status_code=204)
async def delete_tree(tree_id: int, db: AsyncSession = Depends(get_db)):
    # 检查是否存在
    await check_tree_exist(db, tree_id)

    # 无外键依赖，直接删除
    await db.execute(
        text("DELETE FROM behavior_tree WHERE id = :id"),
        {"id": tree_id}
    )
    await db.commit()
    # 204 No Content