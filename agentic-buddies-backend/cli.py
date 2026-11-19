"""Agentic Buddies 管理 CLI。

用法:
    python cli.py reset-password [username]

username 缺省为 admin。密码重置为 conf.yaml 中
auth.default_reset_password 配置的默认密码。
重置会同时清零防爆破失败计数、解除锁定并启用账户。
"""
import argparse
import asyncio
import sys

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import text, table, column, update as sql_update

from sql.sql_connect import engine
from config import get_default_reset_password

load_dotenv()

# SQLAlchemy Core 表定义（UPDATE 使用表达式，避免字符串拼接 SQL）
users_table = table(
    "users",
    column("id"),
    column("username"),
    column("password_hash"),
    column("is_enabled"),
    column("is_admin"),
    column("attmpts"),
    column("last_failed_attempt"),
)

# 重置后的默认密码从 conf.yaml 的 auth.default_reset_password 读取；
# 未配置时失败关闭，禁止回退到硬编码密码。
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """使用 bcrypt 生成密码哈希。

    Args:
        password: 明文密码，超过 72 字节部分按 bcrypt 规则截断。

    Returns:
        bcrypt 哈希字符串。
    """
    password_bytes = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


async def reset_user_password(username: str, new_password: str) -> bool:
    """重置指定用户密码，并清零防爆破状态、启用账户。

    Args:
        username: 目标用户名。
        new_password: 新的明文密码。

    Returns:
        用户存在并重置成功返回 True，用户不存在返回 False。
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text("SELECT id, username FROM users WHERE username = :username"),
            {"username": username}
        )
        row = result.fetchone()
        if row is None:
            return False

        stmt = (
            sql_update(users_table)
            .where(users_table.c.id == row.id)
            .values(
                password_hash=hash_password(new_password),
                attmpts=0,
                last_failed_attempt=None,
                is_enabled=True,
            )
        )
        await conn.execute(stmt)
    return True


async def cmd_reset_password(args: argparse.Namespace) -> int:
    """reset-password 子命令处理函数：将密码重置为配置的默认密码。

    Args:
        args: 命令行参数，包含 username。

    Returns:
        进程退出码，0 成功，1 失败。
    """
    default_password = get_default_reset_password()
    if not default_password:
        print("错误: 未配置默认重置密码，请检查 conf.yaml 的 auth.default_reset_password")
        return 1

    try:
        success = await reset_user_password(args.username, default_password)
    except Exception as exc:
        print(f"错误: 数据库操作失败: {exc}")
        return 1

    if not success:
        print(f"错误: 用户 '{args.username}' 不存在")
        return 1

    print(f"用户 '{args.username}' 密码已重置为初始密码，防爆破计数已清零，账户已启用")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    Returns:
        配置完成的 ArgumentParser。
    """
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Agentic Buddies 系统管理 CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    reset_parser = subparsers.add_parser(
        "reset-password",
        help="重置用户密码（同时清零防爆破计数并启用账户）"
    )
    reset_parser.add_argument(
        "username",
        nargs="?",
        default="admin",
        help="目标用户名，缺省为 admin"
    )
    return parser


async def async_main() -> int:
    """CLI 异步入口。

    Returns:
        进程退出码。
    """
    args = build_parser().parse_args()
    try:
        if args.command == "reset-password":
            return await cmd_reset_password(args)
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(async_main()))
