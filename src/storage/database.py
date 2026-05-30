"""PipelineDB —— 单一 SQLite 数据库，存储所有翻译条目的完整生命周期。

用法:
    db = PipelineDB(ctx.output_dir / "pipeline.db")
    db.execute("INSERT OR REPLACE INTO entries (...) VALUES (...)", (...))
    db.commit()
    db.close()
"""
import sqlite3
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════
# Schema
# ═══════════════════════════════════════════════════════════

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS entries (
    key       TEXT PRIMARY KEY,
    en        TEXT DEFAULT '',
    zh        TEXT DEFAULT '',
    format    TEXT DEFAULT '',
    namespace TEXT DEFAULT '',
    version   TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    slug      TEXT DEFAULT '',
    old_en    TEXT DEFAULT '',
    old_zh    TEXT DEFAULT '',
    state     INTEGER DEFAULT 0,
    verdict   INTEGER DEFAULT 0,
    suggestion TEXT DEFAULT '',
    diagnoses TEXT DEFAULT '[]'
);
"""


# ═══════════════════════════════════════════════════════════
# PipelineDB
# ═══════════════════════════════════════════════════════════


class PipelineDB:
    """与 `ctx.output_dir / "pipeline.db"` 绑定的 SQLite 数据库。
    薄封装：仅提供 execute / commit / close 及上下文管理器。
    """

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> sqlite3.Cursor:
        """执行 SQL，返回 cursor（可用于 fetchall/fetchone）。"""
        if params is None:
            return self._conn.execute(sql)
        return self._conn.execute(sql, params)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False
