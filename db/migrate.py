"""
数据库迁移脚本 — 用 ALTER TABLE 给已有表添加新列（SQLite 兼容）
"""

import logging
from sqlalchemy import text, inspect
from db.database import engine

logger = logging.getLogger(__name__)


def _column_exists(table_name: str, column_name: str) -> bool:
    """检查表中是否已有某列"""
    insp = inspect(engine)
    columns = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in columns


def run_migrations():
    """执行所有待迁移项"""
    migrations = [
        ("parents", "password", "TEXT"),
        ("parents", "totp_secret", "TEXT"),
    ]

    with engine.connect() as conn:
        for table, column, col_type in migrations:
            if not _column_exists(table, column):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
                logger.info("迁移完成: %s.%s 已添加", table, column)
            else:
                logger.debug("跳过迁移: %s.%s 已存在", table, column)
