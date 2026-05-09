"""
共享术语验证模块 — 合并四处独立的停用词/术语有效性检查逻辑。
导出:
    STOP_WORDS: set[str] — 从 config term_blacklist 懒加载、缓存一次的停用词集合
    is_valid_term(term: str) -> bool — 统一术语有效性检查
"""
import re

_STOP_WORDS_CACHE: set[str] | None = None


def _load_stop_words() -> set[str]:
    global _STOP_WORDS_CACHE
    if _STOP_WORDS_CACHE is not None:
        return _STOP_WORDS_CACHE
    try:
        from src import config as cfg
        _STOP_WORDS_CACHE = {w.lower() for w in cfg.get("term_blacklist", []) if isinstance(w, str)}
    except ImportError:
        _STOP_WORDS_CACHE = set()
    return _STOP_WORDS_CACHE


STOP_WORDS: set[str] = _load_stop_words()


def is_valid_term(term: str) -> bool:
    t = term.strip().lower()
    if not t or len(t) <= 2:
        return False
    if re.search(r"\d", t):
        return False
    if re.fullmatch(r"[0-9._-]+", t):
        return False
    try:
        stop = _load_stop_words()
        if t in stop:
            return False
        for word in t.split():
            if word in stop:
                return False
        return True
    except ImportError:
        return True
