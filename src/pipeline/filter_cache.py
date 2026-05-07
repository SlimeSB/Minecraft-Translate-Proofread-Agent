"""Phase 5 Filter 持久化缓存 —— 已迁移至 pipeline.db 的 filter_cache 表。

此模块保留为兼容层，委托给 PipelineDB。
新代码应直接使用 `db.lookup_filter_cache()` / `db.store_filter_cache()`。
"""
import hashlib
from pathlib import Path
from typing import Any

from src.storage.database import PipelineDB


def _cache_key(v: dict[str, Any]) -> str:
    raw = ":".join([
        v.get("key", ""),
        v.get("verdict", ""),
        v.get("zh_current", "")[:150],
        v.get("reason", "")[:200],
    ])
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()


class FilterCache:
    """兼容层 —— 包装 PipelineDB 的 filter_cache 表。"""

    def __init__(self, db_or_path: PipelineDB | Path):
        if isinstance(db_or_path, PipelineDB):
            self._db = db_or_path
        else:
            self._db = PipelineDB(db_or_path)

    @property
    def size(self) -> int:
        return self._db.filter_cache_size()

    def lookup(self, v: dict[str, Any]) -> tuple[str, str] | None:
        return self._db.lookup_filter_cache(_cache_key(v))

    def store(self, v: dict[str, Any], action: str, cleaned_reason: str) -> None:
        self._db.store_filter_cache(_cache_key(v), action, cleaned_reason)

    def save(self) -> None:
        self._db.commit_filter_cache()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.save()
        return False
