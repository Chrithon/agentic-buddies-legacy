"""
Harness 核心数据模型 — 引擎无关设计
顺序：配置 → 记忆 → 知识库 → 行为树 → 引擎通信

行为树约定：
- 一个行为树（BehaviorTree）是一个原子执行单元，由 Harness 一次性输出给引擎
- 内部可由组合节点（Sequence/Selector/Parallel）组织多个子节点
- 模板（BehaviorTreeTemplate）存储在数据库，可实例化为运行时行为树
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid


# ============================================================
# 1. 配置模型（从数据库读取）
# ============================================================

class NPCConfig(BaseModel):
    """NPC 配置，对应数据库 npcs 表"""
    id: int
    name: str
    model_map: Dict[str, str] = Field(alias="model_config")   # Pydantic 保留字, 用 alias 映射 DB 列
    character_prompt: Optional[str] = None
    related_world: Optional[int] = None
    is_enabled: bool = False
    owner: int


class LLMProvider(BaseModel):
    """LLM 服务商配置，对应数据库 llm_providers 表"""
    id: int
    provider_id: str
    show_name: str
    api_key: Optional[str] = None
    base_url: str
    models: List[Dict[str, Any]] = []


class WorldConfig(BaseModel):
    """世界观配置，对应数据库 worlds 表（用于知识库隔离）"""
    id: int
    name: str
    description: Optional[str] = None
    world_prompt: str
    kb_api_url: Optional[str] = None               # 知识库 API 地址
    kb_api_headers: Dict[str, Any] = Field(default_factory=dict)   # 知识库 API 请求头
    kb_api_timeout: Optional[int] = 30             # 知识库 API 超时（秒）


# ============================================================
# 2. 记忆模型（TeleMem / Mem0 兼容）
# ============================================================

class MemoryItem(BaseModel):
    """单条记忆条目，对齐 TeleMem/Mem0 API 返回字段"""
    id: str
    memory: str
    event: Optional[str] = None          # ADD / UPDATE / DELETE
    score: Optional[float] = None        # search() 返回的相似度分值
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None   # TeleMem 可能返回 null


class TeleMemResponse(BaseModel):
    """TeleMem add() / search() 的响应包装"""
    results: List[MemoryItem] = Field(default_factory=list)


class MemoryContext(BaseModel):
    """组装到 NPC 对话上下文的记忆快照（应用层模型）"""
    session_uuid: str
    history: List[MemoryItem] = Field(default_factory=list)
    summary: Optional[str] = None


# ============================================================
# 4. 行为树模型
# ============================================================

# 4.1 节点类型枚举
class NodeType(str, Enum):
    """行为树节点类型"""
    ACTION = "action"
    CONDITION = "condition"
    SEQUENCE = "sequence"
    SELECTOR = "selector"
    PARALLEL = "parallel"


class ActionType(str, Enum):
    """原子动作类型 —— 每个动作节点做一件事"""
    # 移动
    MOVE_TO = "move_to"
    FOLLOW = "follow"
    STOP = "stop"
    # 交互
    SAY = "say"
    EMOTE = "emote"
    INTERACT = "interact"
    USE_ITEM = "use_item"
    ATTACK = "attack"
    # 扩展
    WAIT = "wait"
    GATHER = "gather"
    CRAFT = "craft"
    TRADE = "trade"


class ConditionType(str, Enum):
    """原子条件类型 —— 每个条件节点判断一件事"""
    HAS_ITEM = "has_item"
    HEALTH_ABOVE = "health_above"
    HEALTH_BELOW = "health_below"
    DISTANCE_TO_PLAYER = "distance_to_player"
    HAS_TARGET = "has_target"
    IS_IN_WORLD = "is_in_world"


# 4.2 行为树节点（递归结构）
class BehaviorNode(BaseModel):
    """
    行为树节点 —— 原子化设计
    一个节点只做一件事，组合节点决定执行顺序
    """
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    node_type: NodeType

    # ---- 动作节点字段 ----
    action_type: Optional[ActionType] = None
    action_params: Dict[str, Any] = Field(default_factory=dict)

    # ---- 条件节点字段 ----
    condition_type: Optional[ConditionType] = None
    condition_params: Dict[str, Any] = Field(default_factory=dict)

    # ---- 组合节点字段 ----
    children: Optional[List["BehaviorNode"]] = None
    parallel_policy: Optional[str] = None  # "all_succeed" / "any_succeed"

    # ---- 元信息 ----
    description: Optional[str] = None


# 支持递归引用
BehaviorNode.model_rebuild()


# 4.3 行为树模板（数据库存储）
class BehaviorTreeTemplate(BaseModel):
    """
    数据库中的行为树模板（预设、可复用）
    对应 public.behavior_tree 表
    一个模板代表一个完整的原子行为树，可被实例化后发送给引擎执行
    """
    id: int
    name: str
    description: Optional[str] = None
    tree_definition: Dict[str, Any]  # JSONB → 实际是 BehaviorNode 结构

    def to_behavior_tree(self, npc_id: int, tree_name: Optional[str] = None) -> "BehaviorTree":
        """将模板实例化为可执行的行为树（运行时发送给引擎）"""
        return BehaviorTree(
            npc_id=npc_id,
            name=tree_name or self.name,
            root=BehaviorNode(**self.tree_definition)
        )


# 4.4 运行时行为树（Harness 输出 → 引擎执行）
class BehaviorTree(BaseModel):
    """
    Harness 运行时生成的最小可执行单元
    一个行为树就是原子任务，由 Harness 一次性输出给引擎适配层执行
    内部可由组合节点（Sequence/Selector/Parallel）组织多个子节点
    """
    tree_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    npc_id: int
    name: Optional[str] = None          # 可选，用于调试
    root: BehaviorNode                  # 根节点，可以是动作、条件或组合节点
    generated_at: Optional[int] = None  # 时间戳
    latency_ms: int = 0                 # 生成耗时


# ============================================================
# 5. 引擎通信模型（引擎 ↔ Harness）
# ============================================================

class NPCState(BaseModel):
    """游戏引擎定期上报的 NPC 状态"""
    npc_id: int
    position: List[float] = [0.0, 0.0, 0.0]
    rotation: Optional[List[float]] = None
    health: float = 100.0
    current_action: Optional[str] = None
    inventory: List[str] = Field(default_factory=list)
    world_id: Optional[int] = None
    target_id: Optional[int] = None


class InteractionRequest(BaseModel):
    """来自游戏引擎的请求"""
    npc_id: int
    player_id: Optional[str] = None
    type: str = "text"  # "text" | "event" | "state_update"
    text: Optional[str] = None
    event: Optional[Dict[str, Any]] = None
    session_uuid: Optional[str] = None
    current_state: Optional[NPCState] = None


class InteractionResponse(BaseModel):
    """Harness 返回给游戏引擎的响应 — 核心是行为树"""
    session_uuid: str
    behavior_tree: Optional[BehaviorTree] = None   # 最小可执行单元
    reply_text: Optional[str] = None                # 可选显示文本
    latency_ms: int = 0
    flagged: bool = False
    flagged_category: Optional[str] = None