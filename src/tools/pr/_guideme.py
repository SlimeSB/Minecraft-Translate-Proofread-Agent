"""PR 审校 — GuideME 文档对齐（向后兼容重定向）。

已重构为通用的 _manual_aligner 模块。
"""
from typing import Any

from src.tools.pr._manual_aligner import align as _align


def match(path: str) -> dict[str, str] | None:
    """已弃用。保留以兼容旧调用方。"""
    return None


def align(
    changed_files: list[dict[str, Any]],
    raw_base: str,
    raw_head: str,
    raw_get_fn,
    token: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """已弃用，重定向到 _manual_aligner.align。"""
    return _align(changed_files, raw_base, raw_head, raw_get_fn, token)
