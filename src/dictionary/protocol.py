"""DictStore Protocol — 所有词典存储的统一接口。"""

import sqlite3
from typing import Any, Callable, Literal, Protocol

from src.logging import warn


class LookupMode:
    MIXED: Literal["mixed"] = "mixed"
    SHORT: Literal["short"] = "short"

LookupModeStr = Literal["mixed", "short"]


class DictStore(Protocol):
    def lookup(self, en_text: str, mode: LookupModeStr = LookupMode.MIXED, **kwargs: Any) -> str: ...

    def load(self) -> None: ...

    def close(self) -> None: ...


def collect_hints(
    en_text: str,
    stores: list,
    *,
    mode: LookupModeStr | None = None,
    mode_fn: Callable[[object], LookupModeStr] | None = None,
    sep: str = "\n",
    **kwargs: Any,
) -> str:
    """依次查询所有词典存储，拼接结果为提示文本。

    mode: 统一模式（所有 store 使用相同模式）
    mode_fn(store) -> LookupModeStr: 逐 store 决定模式
    """
    parts: list[str] = []
    for store in stores:
        try:
            store_mode = mode_fn(store) if mode_fn else (mode or LookupMode.MIXED)
            hint = store.lookup(en_text, mode=store_mode, **kwargs)
            if hint:
                parts.append(hint)
        except Exception:
            pass
    return sep.join(parts)


def setup_fts(
    conn: sqlite3.Connection,
    fts_table: str,
    fts_columns: str,
    content_table: str,
    label: str = "",
) -> bool:
    """在 SQLite 连接上创建 FTS5 虚表并重建索引。

    Returns:
        True 表示 FTS5 已启用，False 表示降级为普通索引查询。
    """
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts_table} "
            f"USING fts5({fts_columns}, content={content_table}, content_rowid=rowid)"
        )
        conn.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES('rebuild')")
        return True
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        warn(f"[{label}] FTS5 创建失败 ({e})，降级为索引查询")
        try:
            conn.execute(f"DROP TABLE IF EXISTS {fts_table}")
        except sqlite3.OperationalError:
            pass
    return False
