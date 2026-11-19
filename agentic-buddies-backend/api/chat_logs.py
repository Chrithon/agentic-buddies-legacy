from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from sql.sql_connect import get_db

router = APIRouter()

# ---------- Pydantic 模型 ----------
class LogResponse(BaseModel):
    id: int
    npc_role_id: int
    player_uuid: Optional[str]
    session_uuid: Optional[str]
    player_input: str
    npc_response: str
    config: dict = Field(alias="model_config")
    latency_ms: Optional[int]
    success: bool
    error_message: Optional[str]
    flagged: bool
    flagged_category: Optional[str]
    alert_required: bool = False
    exec_step: Optional[dict] = None
    created_at: datetime

# ---------- 列表（支持筛选） ----------
@router.get("/", response_model=List[LogResponse])
async def list_logs(
    npc_role_id: Optional[int] = Query(None, description="按 NPC ID 筛选"),
    session_uuid: Optional[str] = Query(None, description="按会话 UUID 筛选"),
    flagged: Optional[bool] = Query(None, description="是否触发安全拦截"),
    alert_required: Optional[bool] = Query(None, description="是否需要告警"),
    limit: int = Query(100, description="返回条数上限", ge=1, le=1000),
    offset: int = Query(0, description="偏移量", ge=0),
    db: AsyncSession = Depends(get_db)
):
    query = """
        SELECT id, npc_role_id, player_uuid, session_uuid,
               player_input, npc_response, model_config,
               latency_ms, success, error_message,
               flagged, flagged_category, alert_required, exec_step, created_at
        FROM conversation_logs
        WHERE 1=1
    """
    params = {}

    if npc_role_id is not None:
        query += " AND npc_role_id = :npc_role_id"
        params["npc_role_id"] = npc_role_id

    if session_uuid is not None:
        query += " AND session_uuid = :session_uuid"
        params["session_uuid"] = session_uuid

    if flagged is not None:
        query += " AND flagged = :flagged"
        params["flagged"] = flagged

    if alert_required is not None:
        query += " AND alert_required = :alert_required"
        params["alert_required"] = alert_required

    query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    result = await db.execute(text(query), params)
    rows = result.fetchall()
    return [
        {
            "id": row.id,
            "npc_role_id": row.npc_role_id,
            "player_uuid": str(row.player_uuid) if row.player_uuid else None,
            "session_uuid": str(row.session_uuid) if row.session_uuid else None,
            "player_input": row.player_input,
            "npc_response": row.npc_response,
            "model_config": row.model_config,
            "latency_ms": row.latency_ms,
            "success": row.success,
            "error_message": row.error_message,
            "flagged": row.flagged,
            "flagged_category": row.flagged_category,
            "alert_required": row.alert_required,
            "exec_step": row.exec_step if isinstance(row.exec_step, dict) else None,
            "created_at": row.created_at,
        }
        for row in rows
    ]

# ---------- 获取单条日志详情 ----------
@router.get("/{log_id}", response_model=LogResponse)
async def get_log(log_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("""
            SELECT id, npc_role_id, player_uuid, session_uuid,
                   player_input, npc_response, model_config,
                   latency_ms, success, error_message,
                   flagged, flagged_category, alert_required, exec_step, created_at
            FROM conversation_logs
            WHERE id = :id
        """),
        {"id": log_id}
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="日志记录不存在")
    return {
        "id": row.id,
        "npc_role_id": row.npc_role_id,
        "player_uuid": str(row.player_uuid) if row.player_uuid else None,
        "session_uuid": str(row.session_uuid) if row.session_uuid else None,
        "player_input": row.player_input,
        "npc_response": row.npc_response,
        "model_config": row.model_config,
        "latency_ms": row.latency_ms,
        "success": row.success,
        "error_message": row.error_message,
        "flagged": row.flagged,
        "flagged_category": row.flagged_category,
        "alert_required": row.alert_required,
        "exec_step": row.exec_step if isinstance(row.exec_step, dict) else None,
        "created_at": row.created_at,
    }