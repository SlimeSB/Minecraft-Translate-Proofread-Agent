"""
外部社区翻译词典 — 按需 SQLite 查询 900K+ 条历史翻译记录，
按 EN 原文匹配后，按 ZH 译文分组注入 LLM 提示词。

不再全量加载到内存，每次 lookup 直接查询 SQLite。
"""
import re
import sqlite3
from pathlib import Path

from src.logging import warn

DEFAULT_DB_PATH = "data/Dict-Sqlite.db"
DEFAULT_LEMMA_PATH = "data/lemma_cache.json"

_RE_WORD = re.compile(r"[A-Za-z]+")

_STOP_WORDS: set[str] = set()


def _load_stop_words() -> set[str]:
    global _STOP_WORDS
    if _STOP_WORDS:
        return _STOP_WORDS
    try:
        from src import config as cfg
        _STOP_WORDS = {w.lower() for w in cfg.get("term_blacklist", []) if isinstance(w, str)}
    except Exception as e:
        warn(f"[停用词] 加载停用词失败: {type(e).__name__}: {e}")
    return _STOP_WORDS


class ExternalDictStore:
    """按需查询外部 SQLite 词典，避免全量内存加载（~200-300MB）。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH, lemma_cache_path: str = DEFAULT_LEMMA_PATH):
        self._conn: sqlite3.Connection | None = None
        self._lemma_map: dict[str, str] = {}
        self._loaded = False
        self._db_path = db_path
        self._lemma_cache_path = lemma_cache_path

    def load(self) -> None:
        if self._loaded:
            return
        self._load_lemma_cache()
        db_path = Path(self._db_path)
        if not db_path.exists():
            print(f"[ExternalDict] 词典文件不存在: {db_path}")
            self._loaded = True
            return
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        # 加速按 EN 原文查询（首次加载时创建索引）
        try:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_dict_origin_lower "
                "ON dict(LOWER(ORIGIN_NAME))"
            )
        except sqlite3.OperationalError:
            warn(f"[ExternalDict] 索引创建失败（可能为只读文件系统）")
        total = self._conn.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
        unique = self._conn.execute(
            "SELECT COUNT(DISTINCT LOWER(ORIGIN_NAME)) FROM dict"
        ).fetchone()[0]
        self._loaded = True
        print(f"[ExternalDict] 就绪: {unique} 个唯一 EN 词条, {total} 条总记录（按需查询模式）")

    def _load_lemma_cache(self) -> None:
        import json
        cache_path = Path(self._lemma_cache_path)
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for canonical, entry in data.items():
                    variants = entry.get("variants", [canonical])
                    for v in variants:
                        vk = v.lower().strip()
                        if vk not in self._lemma_map:
                            self._lemma_map[vk] = canonical
            except (json.JSONDecodeError, IOError):
                self._lemma_map = {}

    def _query_word(self, word_lower: str) -> list[tuple[str, str]]:
        """查询单个英文单词的翻译记录，返回 [(zh, modid), ...]."""
        if self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT TRANS_NAME, MODID FROM dict WHERE LOWER(ORIGIN_NAME) = ?",
            (word_lower,),
        ).fetchall()
        return [(r["TRANS_NAME"], r["MODID"]) for r in rows]

    def lookup(self, en_text: str, max_groups: int = 3, max_modids: int = 5) -> str:
        """在 EN 原文中搜索已知翻译，返回注入文本（空串表示无匹配）。"""
        if not self._loaded:
            self.load()
        if self._conn is None:
            return ""

        words = _RE_WORD.findall(en_text)
        if not words:
            return ""

        stop_words = _load_stop_words()
        pairs: dict[tuple[str, str], set[str]] = {}  # (en_word, zh) -> {modids}
        seen: set[tuple[str, str]] = set()

        for w in words:
            w_lower = w.lower()
            if w_lower in stop_words:
                continue
            candidates = self._query_word(w_lower)
            if not candidates:
                canon = self._lemma_map.get(w_lower)
                if canon:
                    canon_lower = canon.lower()
                    if canon_lower != w_lower:
                        candidates = self._query_word(canon_lower)
            if not candidates:
                continue

            for zh, modid in candidates:
                pair_key = (w, zh)
                if pair_key in seen:
                    pairs[pair_key].add(modid)
                else:
                    seen.add(pair_key)
                    pairs[pair_key] = {modid}

        if not pairs:
            return ""

        sorted_pairs = sorted(pairs.items(), key=lambda x: -len(x[1]))
        lines: list[str] = []
        for (en_word, zh), modids in sorted_pairs[:max_groups]:
            modid_list = sorted(modids)[:max_modids]
            modid_str = ", ".join(modid_list)
            if len(modids) > max_modids:
                modid_str += f" +{len(modids) - max_modids}"
            lines.append(f"\"{en_word}\" -> \"{zh}\" 来源Mod: [{modid_str}]")

        if not lines:
            return ""
        return "  外部词典: " + " | ".join(lines)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
