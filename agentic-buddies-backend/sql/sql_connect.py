import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from typing import AsyncGenerator

# 加载环境变量
load_dotenv()

# 从环境变量获取数据库连接字符串
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL 环境变量未设置，请检查 .env 文件")

# 创建异步数据库引擎
engine = create_async_engine(
    DATABASE_URL,
    echo=True,  # 启用 SQL 日志输出以便调试
    pool_size=10,
    max_overflow=20
)

# 创建异步 session 工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# 创建 Base 类
Base = declarative_base()

# 依赖注入函数，用于获取数据库会话
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# 测试数据库连接
async def connection_test() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"数据库连接测试失败: {e}")
        return False
