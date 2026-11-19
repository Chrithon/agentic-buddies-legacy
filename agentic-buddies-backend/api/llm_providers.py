import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text, table, column, update as sql_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel

from sql.sql_connect import get_db

router = APIRouter()

# SQLAlchemy Core 表定义（用于安全的 UPDATE 表达式，避免 f-string 拼接 SQL）
llm_providers_table = table(
    "llm_providers",
    column("id"),
    column("provider_id"),
    column("show_name"),
    column("api_key"),
    column("base_url"),
    column("models", JSONB),
)

# ---------- Pydantic 模型 ----------
class ProviderCreate(BaseModel):
    provider_id: str          # 唯一标识，如 "deepseek"
    show_name: str            # 显示名称，如 "DeepSeek"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: List[dict] = []   # 默认为空列表

class ProviderUpdate(BaseModel):
    provider_id: Optional[str] = None
    show_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: Optional[List[dict]] = None

class ProviderResponse(BaseModel):
    id: int
    provider_id: str
    show_name: str
    api_key: Optional[str]
    base_url: Optional[str]
    models: List[dict]

# ---------- 辅助函数 ----------
async def check_provider_exist(db: AsyncSession, provider_id: int) -> dict:
    """根据主键 ID 获取服务商，不存在则 404"""
    result = await db.execute(
        text("""
            SELECT id, provider_id, show_name, api_key, base_url, models
            FROM llm_providers
            WHERE id = :id
        """),
        {"id": provider_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="模型服务商不存在")
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "show_name": row.show_name,
        "api_key": row.api_key,
        "base_url": row.base_url,
        "models": row.models,  # 已是 dict/list
    }

# ---------- 1. 列表 ----------
@router.get("/", response_model=List[ProviderResponse])
async def list_providers(db: AsyncSession = Depends(get_db)):
    """列出所有模型服务商"""
    result = await db.execute(
        text("""
            SELECT id, provider_id, show_name, api_key, base_url, models
            FROM llm_providers
            ORDER BY id
        """)
    )
    rows = result.fetchall()
    return [
        {
            "id": row.id,
            "provider_id": row.provider_id,
            "show_name": row.show_name,
            "api_key": row.api_key,
            "base_url": row.base_url,
            "models": row.models,
        }
        for row in rows
    ]

# ---------- 2. 创建 ----------
@router.post("/", response_model=ProviderResponse, status_code=201)
async def create_provider(provider: ProviderCreate, db: AsyncSession = Depends(get_db)):
    """
    创建新的模型服务商。
    注意：provider_id 必须唯一，否则会报错（数据库 UNIQUE 约束）。
    """
    # 检查 provider_id 是否已存在（可选，因为数据库会抛出唯一冲突，但我们可以提前返回友好信息）
    check = await db.execute(
        text("SELECT id FROM llm_providers WHERE provider_id = :provider_id"),
        {"provider_id": provider.provider_id}
    )
    if check.fetchone():
        raise HTTPException(status_code=400, detail="provider_id 已被占用")

    # 插入新记录
    result = await db.execute(
        text("""
            INSERT INTO llm_providers (provider_id, show_name, api_key, base_url, models)
            VALUES (:provider_id, :show_name, :api_key, :base_url, :models)
            RETURNING id, provider_id, show_name, api_key, base_url, models
        """),
        {
            "provider_id": provider.provider_id,
            "show_name": provider.show_name,
            "api_key": provider.api_key,
            "base_url": provider.base_url,
            "models": json.dumps(provider.models),
        }
    )
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "show_name": row.show_name,
        "api_key": row.api_key,
        "base_url": row.base_url,
        "models": row.models,
    }

# ---------- 3. 详情 ----------
@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """通过主键 ID 获取详情"""
    return await check_provider_exist(db, provider_id)

# ---------- 从提供商拉取模型列表 ----------
class FetchModelsRequest(BaseModel):
    base_url: str
    api_key: Optional[str] = None

class FetchModelsResponse(BaseModel):
    models: List[dict]

# OpenRouter 公共模型目录（免鉴权），用于补全上下文长度
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_openrouter_cache: dict = {"fetched_at": None, "context_map": {}}
OPENROUTER_CACHE_TTL = timedelta(hours=1)


def extract_context_length(item: dict) -> Optional[int]:
    """从提供商返回的单个模型对象中提取上下文长度。

    兼容常见变体：OpenRouter 的 context_length、vLLM 的 max_model_len、
    OpenRouter 列表接口的 top_provider.context_length。
    """
    for key in ("context_length", "max_model_len"):
        value = item.get(key)
        if isinstance(value, int) and value > 0:
            return value
    top_provider = item.get("top_provider")
    if isinstance(top_provider, dict):
        value = top_provider.get("context_length")
        if isinstance(value, int) and value > 0:
            return value
    return None


async def get_openrouter_context_map() -> dict:
    """获取 OpenRouter 公共目录的 模型id -> context_length 映射（带 1 小时内存缓存）。

    目录不可用时返回空字典，不影响主流程。
    """
    now = datetime.now(timezone.utc)
    fetched_at = _openrouter_cache["fetched_at"]
    if fetched_at and now - fetched_at < OPENROUTER_CACHE_TTL:
        return _openrouter_cache["context_map"]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(OPENROUTER_MODELS_URL)
        if response.status_code != 200:
            return _openrouter_cache["context_map"]
        data = response.json()
        context_map = {}
        for item in data.get("data", []):
            model_id = item.get("id")
            context_length = item.get("context_length")
            if model_id and isinstance(context_length, int) and context_length > 0:
                context_map[model_id] = context_length
        _openrouter_cache["fetched_at"] = now
        _openrouter_cache["context_map"] = context_map
        return context_map
    except (httpx.RequestError, ValueError):
        return _openrouter_cache["context_map"]


def match_openrouter_context(model_name: str, context_map: dict) -> Optional[int]:
    """按模型 id 匹配 OpenRouter 目录。

    精确匹配优先；其次匹配 "<org>/<model_name>" 形式的后缀
    （如 deepseek-chat 匹配 deepseek/deepseek-chat）。
    """
    if model_name in context_map:
        return context_map[model_name]
    suffix = f"/{model_name}"
    for model_id, context_length in context_map.items():
        if model_id.endswith(suffix):
            return context_length
    return None


@router.post("/fetch-models", response_model=FetchModelsResponse)
async def fetch_models(request: FetchModelsRequest) -> FetchModelsResponse:
    """从 OpenAI 兼容接口 `{base_url}/models` 拉取模型列表。

    作为代理转发，避免前端直连提供商时的 CORS 问题。
    上下文长度按三级策略获取：提供商响应自带字段 → OpenRouter 公共目录匹配 → 留空。
    返回统一格式：[{"name": "<model_id>", "context_length": <int|null>}, ...]
    """
    base_url = request.base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="base_url 必须以 http:// 或 https:// 开头")

    headers = {}
    if request.api_key:
        headers["Authorization"] = f"Bearer {request.api_key}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail="请求提供商接口超时")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"无法连接提供商接口: {exc.__class__.__name__}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"提供商接口返回错误（HTTP {response.status_code}），请检查 base_url 与 api_key"
        )

    try:
        data = response.json()
        items = data.get("data", [])
        models = [
            {"name": item["id"], "context_length": extract_context_length(item)}
            for item in items
        ]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=502, detail="提供商接口返回格式无法解析（期望 OpenAI 兼容格式）")

    if not models:
        raise HTTPException(status_code=502, detail="提供商接口未返回任何模型")

    # 对缺失上下文长度的模型，尝试从 OpenRouter 公共目录补全
    if any(m["context_length"] is None for m in models):
        context_map = await get_openrouter_context_map()
        for model in models:
            if model["context_length"] is None:
                model["context_length"] = match_openrouter_context(model["name"], context_map)

    return FetchModelsResponse(models=models)

# ---------- 4. 更新 ----------
@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: int,
    update: ProviderUpdate,
    db: AsyncSession = Depends(get_db)
):
    """部分更新服务商信息，只提供需要修改的字段即可"""
    # 检查存在性
    await check_provider_exist(db, provider_id)

    # 收集需要更新的字段（SQLAlchemy Core 自动参数绑定，杜绝 SQL 注入）
    update_values = {}

    if update.provider_id is not None:
        # 检查新的 provider_id 是否已被其他记录占用
        check = await db.execute(
            text("SELECT id FROM llm_providers WHERE provider_id = :provider_id AND id != :id"),
            {"provider_id": update.provider_id, "id": provider_id}
        )
        if check.fetchone():
            raise HTTPException(status_code=400, detail="provider_id 已被其他记录占用")
        update_values["provider_id"] = update.provider_id

    if update.show_name is not None:
        update_values["show_name"] = update.show_name

    if update.api_key is not None:
        update_values["api_key"] = update.api_key

    if update.base_url is not None:
        update_values["base_url"] = update.base_url

    if update.models is not None:
        update_values["models"] = update.models

    if not update_values:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    stmt = (
        sql_update(llm_providers_table)
        .where(llm_providers_table.c.id == provider_id)
        .values(**update_values)
        .returning(
            llm_providers_table.c.id,
            llm_providers_table.c.provider_id,
            llm_providers_table.c.show_name,
            llm_providers_table.c.api_key,
            llm_providers_table.c.base_url,
            llm_providers_table.c.models,
        )
    )
    result = await db.execute(stmt)
    row = result.fetchone()
    await db.commit()
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "show_name": row.show_name,
        "api_key": row.api_key,
        "base_url": row.base_url,
        "models": row.models,
    }

# ---------- 5. 删除 ----------
@router.delete("/{provider_id}", status_code=204)
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """删除服务商（注意：不会级联删除任何其他表）"""
    result = await db.execute(
        text("DELETE FROM llm_providers WHERE id = :id RETURNING id"),
        {"id": provider_id}
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="模型服务商不存在")
    await db.commit()
    # 204 No Content