import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

from api import auth, npc, mcp, world, behavior_tree, llm_providers, word_list, chat_logs, users, block_policy
from sql.sql_connect import engine, connection_test

load_dotenv()

# ==================== 生命周期管理 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---------- 启动时执行 ----------
    print("正在启动 Agentic Buddies Backend...")
    if await connection_test():
        print("数据库连接成功")
    else:
        print("数据库连接失败，请检查 .env 配置")
        raise RuntimeError("无法连接到数据库，服务启动失败")
    yield
    # ---------- 关闭时执行 ----------
    await engine.dispose()
    print("数据库连接池已释放，服务已关闭")

# ==================== 创建 FastAPI 应用 ====================
app = FastAPI(
    title="Agentic Buddies Backend",
    version="1.0.0",
    lifespan=lifespan
)

# ==================== CORS 中间件 ====================
# 允许的源通过环境变量 CORS_ORIGINS 配置（逗号分隔）；
# 未配置时默认仅允许本地开发前端，生产部署必须显式配置为实际域名。
# 注意：allow_credentials=True 时绝不能用 "*" 通配符。
DEFAULT_DEV_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_DEV_ORIGINS).split(",")
    if origin.strip()
]
if "*" in allowed_origins:
    print("警告: CORS_ORIGINS 包含通配符 *，存在安全风险，生产环境请配置具体域名")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 挂载路由 ====================
app.include_router(auth.router, prefix="/api/auth")
app.include_router(users.router, prefix="/api/users")
app.include_router(npc.router, prefix="/api/npcs")
app.include_router(mcp.router, prefix="/api/mcp")
app.include_router(world.router, prefix="/api/worlds")
app.include_router(behavior_tree.router, prefix="/api/behavior-trees")
app.include_router(llm_providers.router, prefix="/api/llm-providers")
app.include_router(word_list.router, prefix="/api/word-list")
app.include_router(chat_logs.router, prefix="/api/logs")
app.include_router(block_policy.router, prefix="/api/block-policies")

# ==================== 根路径 ====================
@app.get("/")
async def root():
    return {"message": "Agentic Buddies API 已启动", "status": "running"}

# ==================== 直接运行入口 ====================
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
