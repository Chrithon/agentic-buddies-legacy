"""PostgreSQL 数据库接入 — 配置由 conf.yaml 驱动"""

from collections.abc import AsyncGenerator
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_conf_path = Path(__file__).resolve().parents[1] / "conf.yaml"
_conf = yaml.safe_load(_conf_path.read_text())["database"]["postgresql"]

DATABASE_URL = (
    f"postgresql+asyncpg://{_conf['user']}:{_conf['password']}"
    f"@{_conf['host']}:{_conf['port']}/{_conf['database']}"
)

_engine = create_async_engine(
    DATABASE_URL,
    echo=_conf.get("echo", False),
    pool_size=_conf.get("pool_size", 10),
    max_overflow=_conf.get("max_overflow", 20),
    pool_pre_ping=True,
)

_async_session_factory = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入 — 获取异步数据库会话"""
    async with _async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
