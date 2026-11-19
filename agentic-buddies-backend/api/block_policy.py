from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text, table, column, update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sql.sql_connect import get_db

router = APIRouter()

# ---------- 常量 ----------
VALID_CATEGORIES = ("political", "sexual", "violence", "suicide", "custom")
VALID_POLICY_TYPES = ("report_only", "warning_prompt", "block", "force_block")
VALID_RISK_LEVELS = (1, 2, 3)

POLICY_TYPE_LABELS = {
    "report_only": "仅报告",
    "warning_prompt": "警告提示",
    "block": "拦截",
    "force_block": "强制拦截",
}
CATEGORY_LABELS = {
    "political": "政治",
    "sexual": "色情",
    "violence": "暴力",
    "suicide": "自杀/自残",
    "custom": "自定义",
}
RISK_LEVEL_LABELS = {
    1: "低风险",
    2: "中风险",
    3: "高风险",
}

# ---------- SQLAlchemy Core 表定义 ----------
block_policy_table = table(
    "block_policy",
    column("id"),
    column("policy_id"),
    column("show_name"),
    column("policy_type"),
    column("category"),
    column("risk_level"),
    column("warning_prompt"),
    column("alert_enabled"),
)

# ---------- Pydantic 模型 ----------
class BlockPolicyCreate(BaseModel):
    policy_id: str = Field(min_length=1, max_length=50)
    show_name: str = Field(min_length=1, max_length=100)
    policy_type: str
    category: str
    risk_level: int
    warning_prompt: Optional[str] = None
    alert_enabled: bool = False

class BlockPolicyUpdate(BaseModel):
    policy_id: Optional[str] = Field(default=None, min_length=1, max_length=50)
    show_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    policy_type: Optional[str] = None
    category: Optional[str] = None
    risk_level: Optional[int] = None
    warning_prompt: Optional[str] = None
    alert_enabled: Optional[bool] = None

class BlockPolicyResponse(BaseModel):
    id: int
    policy_id: str
    show_name: str
    policy_type: str
    category: str
    risk_level: int
    warning_prompt: Optional[str]
    alert_enabled: bool

# ---------- 校验函数 ----------
def validate_policy_type(policy_type: str):
    if policy_type not in VALID_POLICY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"policy_type 必须是 {' / '.join(VALID_POLICY_TYPES)} 之一"
        )

def validate_category(category: str):
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"category 必须是 {' / '.join(VALID_CATEGORIES)} 之一"
        )

def validate_risk_level(risk_level: int):
    if risk_level not in VALID_RISK_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"risk_level 必须是 1（低风险）、2（中风险）或 3（高风险）"
        )

async def check_policy_exist(db: AsyncSession, policy_id: int) -> dict:
    result = await db.execute(
        text("""
            SELECT id, policy_id, show_name, policy_type, category, risk_level,
                   warning_prompt, alert_enabled
            FROM block_policy WHERE id = :id
        """),
        {"id": policy_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="拦截策略不存在")
    return dict(row._mapping)

# ---------- 1. 列表 ----------
@router.get("/", response_model=List[BlockPolicyResponse])
async def list_policies(
    policy_type: Optional[str] = Query(None, description="按策略类型筛选"),
    category: Optional[str] = Query(None, description="按分类筛选"),
    risk_level: Optional[int] = Query(None, description="按风险等级筛选"),
    db: AsyncSession = Depends(get_db)
):
    query = """
        SELECT id, policy_id, show_name, policy_type, category, risk_level,
               warning_prompt, alert_enabled
        FROM block_policy WHERE 1=1
    """
    params = {}
    if policy_type:
        validate_policy_type(policy_type)
        query += " AND policy_type = :policy_type"
        params["policy_type"] = policy_type
    if category:
        validate_category(category)
        query += " AND category = :category"
        params["category"] = category
    if risk_level is not None:
        validate_risk_level(risk_level)
        query += " AND risk_level = :risk_level"
        params["risk_level"] = risk_level
    query += " ORDER BY id"

    result = await db.execute(text(query), params)
    return [dict(row._mapping) for row in result.fetchall()]

# ---------- 2. 创建 ----------
@router.post("/", response_model=BlockPolicyResponse, status_code=201)
async def create_policy(policy: BlockPolicyCreate, db: AsyncSession = Depends(get_db)):
    validate_policy_type(policy.policy_type)
    validate_category(policy.category)
    validate_risk_level(policy.risk_level)

    check = await db.execute(
        text("SELECT id FROM block_policy WHERE policy_id = :policy_id"),
        {"policy_id": policy.policy_id}
    )
    if check.fetchone():
        raise HTTPException(status_code=400, detail="policy_id 已被占用")

    try:
        result = await db.execute(
            text("""
                INSERT INTO block_policy
                    (policy_id, show_name, policy_type, category, risk_level,
                     warning_prompt, alert_enabled)
                VALUES
                    (:policy_id, :show_name, :policy_type, :category, :risk_level,
                     :warning_prompt, :alert_enabled)
                RETURNING id, policy_id, show_name, policy_type, category, risk_level,
                           warning_prompt, alert_enabled
            """),
            {
                "policy_id": policy.policy_id,
                "show_name": policy.show_name,
                "policy_type": policy.policy_type,
                "category": policy.category,
                "risk_level": policy.risk_level,
                "warning_prompt": policy.warning_prompt,
                "alert_enabled": policy.alert_enabled,
            }
        )
        await db.commit()
        return dict(result.fetchone()._mapping)
    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="该 policy_id 或 (分类, 风险等级) 组合已存在"
        )

# ---------- 3. 详情 ----------
@router.get("/{policy_id}", response_model=BlockPolicyResponse)
async def get_policy(policy_id: int, db: AsyncSession = Depends(get_db)):
    return await check_policy_exist(db, policy_id)

# ---------- 4. 更新 ----------
@router.put("/{policy_id}", response_model=BlockPolicyResponse)
async def update_policy(
    policy_id: int,
    update: BlockPolicyUpdate,
    db: AsyncSession = Depends(get_db)
):
    await check_policy_exist(db, policy_id)

    update_values = {}
    if update.policy_id is not None:
        check = await db.execute(
            text("SELECT id FROM block_policy WHERE policy_id = :policy_id AND id != :id"),
            {"policy_id": update.policy_id, "id": policy_id}
        )
        if check.fetchone():
            raise HTTPException(status_code=400, detail="policy_id 已被其他记录占用")
        update_values["policy_id"] = update.policy_id

    if update.show_name is not None:
        update_values["show_name"] = update.show_name

    if update.policy_type is not None:
        validate_policy_type(update.policy_type)
        update_values["policy_type"] = update.policy_type

    if update.category is not None:
        validate_category(update.category)
        update_values["category"] = update.category

    if update.risk_level is not None:
        validate_risk_level(update.risk_level)
        update_values["risk_level"] = update.risk_level

    if update.warning_prompt is not None:
        update_values["warning_prompt"] = update.warning_prompt

    if update.alert_enabled is not None:
        update_values["alert_enabled"] = update.alert_enabled

    if not update_values:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    try:
        stmt = (
            sql_update(block_policy_table)
            .where(block_policy_table.c.id == policy_id)
            .values(**update_values)
            .returning(
                block_policy_table.c.id,
                block_policy_table.c.policy_id,
                block_policy_table.c.show_name,
                block_policy_table.c.policy_type,
                block_policy_table.c.category,
                block_policy_table.c.risk_level,
                block_policy_table.c.warning_prompt,
                block_policy_table.c.alert_enabled,
            )
        )
        result = await db.execute(stmt)
        await db.commit()
        return dict(result.fetchone()._mapping)
    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="该 policy_id 或 (分类, 风险等级) 组合已被占用"
        )

# ---------- 5. 删除 ----------
@router.delete("/{policy_id}", status_code=204)
async def delete_policy(policy_id: int, db: AsyncSession = Depends(get_db)):
    await check_policy_exist(db, policy_id)
    await db.execute(
        text("DELETE FROM block_policy WHERE id = :id"),
        {"id": policy_id}
    )
    await db.commit()
    # 204 No Content
