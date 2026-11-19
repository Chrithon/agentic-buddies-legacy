from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import text, table, column, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator

from sql.sql_connect import get_db

router = APIRouter()

# SQLAlchemy Core 表定义（用于安全的 UPDATE 表达式，避免 f-string 拼接 SQL）
word_list_table = table(
    "word_list",
    column("id"),
    column("word"),
    column("list_type"),
    column("category"),
    column("risk_level"),
)

# ---------- Pydantic 模型 ----------
class WordCreate(BaseModel):
    word: str = Field(min_length=1, max_length=100)  # 数据库 VARCHAR(100)
    list_type: str  # 'blacklist' 或 'whitelist'
    category: Optional[str] = None  # 'political', 'sexual', 'violence', 'suicide', 'custom'，仅黑名单适用
    risk_level: Optional[int] = None  # 1=低风险, 2=中风险, 3=高风险，仅黑名单适用

    @field_validator("word")
    @classmethod
    def _strip_word(cls, value: str) -> str:
        """去除首尾空白；纯空白词条直接拒绝"""
        value = value.strip()
        if not value:
            raise ValueError("word 不能为空")
        return value

    @model_validator(mode="after")
    def _require_blacklist_fields(self) -> "WordCreate":
        """黑名单词条必须带 category + risk_level，否则核心会静默忽略"""
        if self.list_type == "blacklist" and (
            self.category is None or self.risk_level is None
        ):
            raise ValueError("黑名单词条必须指定 category 和 risk_level")
        return self

class WordUpdate(BaseModel):
    word: Optional[str] = Field(default=None, max_length=100)
    list_type: Optional[str] = None
    category: Optional[str] = None
    risk_level: Optional[int] = None

    @field_validator("word")
    @classmethod
    def _strip_word(cls, value: Optional[str]) -> Optional[str]:
        """更新时同样不允许改成空词条"""
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("word 不能为空")
        return value

class WordResponse(BaseModel):
    id: int
    word: str
    list_type: str
    category: Optional[str]
    risk_level: Optional[int]

# ---------- 辅助函数 ----------
def validate_list_type(list_type: str):
    if list_type not in ("blacklist", "whitelist"):
        raise HTTPException(status_code=400, detail="list_type 必须是 'blacklist' 或 'whitelist'")

def validate_category(category: Optional[str]):
    if category is not None and category not in ("political", "sexual", "violence", "suicide", "custom"):
        raise HTTPException(status_code=400, detail="category 必须是 'political', 'sexual', 'violence', 'suicide', 'custom' 之一或为空")

def validate_category_applicable(list_type: str, category: Optional[str]):
    """category 仅适用于黑名单类型，白名单不适用"""
    if list_type == "whitelist" and category is not None:
        raise HTTPException(status_code=400, detail="category 仅适用于黑名单类型，白名单不适用")

def validate_risk_level(risk_level: Optional[int]):
    """risk_level 只能是 1、2、3 或 None"""
    if risk_level is not None and risk_level not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="risk_level 必须是 1（低风险）、2（中风险）或 3（高风险）")

def validate_risk_level_applicable(list_type: str, risk_level: Optional[int]):
    """risk_level 仅适用于黑名单类型，白名单不适用"""
    if list_type == "whitelist" and risk_level is not None:
        raise HTTPException(status_code=400, detail="risk_level 仅适用于黑名单类型，白名单不适用")

async def check_word_exist(db: AsyncSession, word_id: int) -> dict:
    result = await db.execute(
        text("SELECT id, word, list_type, category, risk_level FROM word_list WHERE id = :id"),
        {"id": word_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="词条不存在")
    return {
        "id": row.id,
        "word": row.word,
        "list_type": row.list_type,
        "category": row.category,
        "risk_level": row.risk_level,
    }

# ---------- 1. 列表 ----------
@router.get("/", response_model=List[WordResponse])
async def list_words(
    list_type: Optional[str] = Query(None, description="按类型筛选 blacklist/whitelist"),
    category: Optional[str] = Query(None, description="按分类筛选"),
    risk_level: Optional[int] = Query(None, description="按风险等级筛选 1/2/3"),
    db: AsyncSession = Depends(get_db)
):
    query = "SELECT id, word, list_type, category, risk_level FROM word_list WHERE 1=1"
    params = {}
    if list_type:
        validate_list_type(list_type)
        query += " AND list_type = :list_type"
        params["list_type"] = list_type
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
    rows = result.fetchall()
    return [
        {
            "id": row.id,
            "word": row.word,
            "list_type": row.list_type,
            "category": row.category,
            "risk_level": row.risk_level,
        }
        for row in rows
    ]

# ---------- 2. 创建 ----------
@router.post("/", response_model=WordResponse, status_code=201)
async def create_word(word_in: WordCreate, db: AsyncSession = Depends(get_db)):
    validate_list_type(word_in.list_type)
    validate_category(word_in.category)
    validate_category_applicable(word_in.list_type, word_in.category)
    validate_risk_level(word_in.risk_level)
    validate_risk_level_applicable(word_in.list_type, word_in.risk_level)

    # 检查 word 是否已存在（文档规定 word 全局唯一）
    check = await db.execute(
        text("SELECT id FROM word_list WHERE word = :word"),
        {"word": word_in.word}
    )
    if check.fetchone():
        raise HTTPException(status_code=400, detail="该词条已存在于词库中")

    result = await db.execute(
        text("""
            INSERT INTO word_list (word, list_type, category, risk_level)
            VALUES (:word, :list_type, :category, :risk_level)
            RETURNING id, word, list_type, category, risk_level
        """),
        {
            "word": word_in.word,
            "list_type": word_in.list_type,
            "category": word_in.category,
            "risk_level": word_in.risk_level,
        }
    )
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "word": row.word,
        "list_type": row.list_type,
        "category": row.category,
        "risk_level": row.risk_level,
    }

# ---------- 3. 详情 ----------
@router.get("/{word_id}", response_model=WordResponse)
async def get_word(word_id: int, db: AsyncSession = Depends(get_db)):
    return await check_word_exist(db, word_id)

# ---------- 4. 更新 ----------
@router.put("/{word_id}", response_model=WordResponse)
async def update_word(
    word_id: int,
    update: WordUpdate,
    db: AsyncSession = Depends(get_db)
):
    current = await check_word_exist(db, word_id)

    # 收集需要更新的字段（SQLAlchemy Core 自动参数绑定，杜绝 SQL 注入）
    update_values = {}

    if update.word is not None:
        # 检查新 word 是否与其他记录冲突
        check = await db.execute(
            text("SELECT id FROM word_list WHERE word = :word AND id != :id"),
            {"word": update.word, "id": word_id}
        )
        if check.fetchone():
            raise HTTPException(status_code=400, detail="该词条已被其他记录占用")
        update_values["word"] = update.word

    if update.list_type is not None:
        validate_list_type(update.list_type)
        update_values["list_type"] = update.list_type

    # 更新后的生效类型（用于 category 适用性校验）
    effective_list_type = update.list_type if update.list_type is not None else current["list_type"]

    # 黑名单词条必须始终带 category + risk_level，否则核心会静默忽略
    effective_category = update.category if update.category is not None else current["category"]
    effective_risk_level = update.risk_level if update.risk_level is not None else current["risk_level"]
    if effective_list_type == "blacklist" and (
        effective_category is None or effective_risk_level is None
    ):
        raise HTTPException(
            status_code=400,
            detail="黑名单词条必须指定 category 和 risk_level",
        )

    if update.category is not None:
        validate_category(update.category)
        validate_category_applicable(effective_list_type, update.category)
        update_values["category"] = update.category

    if update.risk_level is not None:
        validate_risk_level(update.risk_level)
        validate_risk_level_applicable(effective_list_type, update.risk_level)
        update_values["risk_level"] = update.risk_level

    # 切换为白名单时，自动清空不再适用的 category 和 risk_level
    if update.list_type == "whitelist":
        if current["category"] is not None:
            update_values["category"] = None
        if current["risk_level"] is not None:
            update_values["risk_level"] = None

    if not update_values:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    stmt = (
        sql_update(word_list_table)
        .where(word_list_table.c.id == word_id)
        .values(**update_values)
        .returning(
            word_list_table.c.id,
            word_list_table.c.word,
            word_list_table.c.list_type,
            word_list_table.c.category,
            word_list_table.c.risk_level,
        )
    )
    result = await db.execute(stmt)
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "word": row.word,
        "list_type": row.list_type,
        "category": row.category,
        "risk_level": row.risk_level,
    }

# ---------- 5. 删除 ----------
@router.delete("/{word_id}", status_code=204)
async def delete_word(word_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("DELETE FROM word_list WHERE id = :id RETURNING id"),
        {"id": word_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="词条不存在")
    await db.commit()
    # 204 No Content