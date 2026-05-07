"""
外部社区翻译词典 — 从 SQLite 加载 900K+ 条历史翻译记录，
按 EN 原文匹配后，按 ZH 译文分组注入 LLM 提示词。
"""
import re
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = "data/Dict-Sqlite.db"
DEFAULT_LEMMA_PATH = "data/lemma_cache.json"

_RE_WORD = re.compile(r"[A-Za-z]+")


class ExternalDictStore:
    """加载外部 SQLite 词典，提供按 EN 原文查询翻译参考。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH, lemma_cache_path: str = DEFAULT_LEMMA_PATH):
        # 全量加载到内存（42万唯一EN词条, 90万条记录, 约200-300MB）
        self._index: dict[str, list[tuple[str, str]]] = {}
        self._lemma_map: dict[str, str] = {}
        self._loaded = False
        self._db_path = db_path
        self._lemma_cache_path = lemma_cache_path

    def load(self) -> None:
        """从 SQLite 加载全部 ORIGIN_NAME → (TRANS_NAME, MODID) 入内存。"""
        if self._loaded:
            return
        self._load_lemma_cache()
        db_path = Path(self._db_path)
        if not db_path.exists():
            print(f"[ExternalDict] 词典文件不存在: {db_path}")
            self._loaded = True
            return
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ORIGIN_NAME, TRANS_NAME, MODID FROM dict"
        ).fetchall()
        conn.close()

        for row in rows:
            en = row["ORIGIN_NAME"]
            zh = row["TRANS_NAME"]
            modid = row["MODID"]
            key_lower = en.lower().strip()
            self._index.setdefault(key_lower, []).append((zh, modid))

        self._loaded = True
        total = sum(len(v) for v in self._index.values())
        print(f"[ExternalDict] 加载完成: {len(self._index)} 个唯一 EN 词条, {total} 条总记录")

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

    def lookup(self, en_text: str, max_groups: int = 3, max_modids: int = 5) -> str:
        """在 EN 原文中搜索已知翻译，返回注入文本（空串表示无匹配）。"""
        if not self._loaded:
            self.load()
        if not self._index:
            return ""

        words = _RE_WORD.findall(en_text)
        if not words:
            return ""

        groups: dict[str, set[str]] = {}
        seen_zh: set[str] = set()

        for w in words:
            w_lower = w.lower()
            candidates = self._index.get(w_lower)
            if not candidates:
                canon = self._lemma_map.get(w_lower)
                if canon:
                    canon_lower = canon.lower()
                    if canon_lower != w_lower:
                        candidates = self._index.get(canon_lower)
            if not candidates:
                continue

            for zh, modid in candidates:
                if zh in seen_zh:
                    groups[zh].add(modid)
                else:
                    seen_zh.add(zh)
                    groups[zh] = {modid}

        if not groups:
            return ""

        sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
        lines: list[str] = []
        for zh, modids in sorted_groups[:max_groups]:
            modid_list = sorted(modids)[:max_modids]
            modid_str = ", ".join(modid_list)
            if len(modids) > max_modids:
                modid_str += f" +{len(modids) - max_modids}"
            lines.append(f"\"{zh}\" 来源Mod: [{modid_str}]")

        if not lines:
            return ""
        return "  外部词典: " + " | ".join(lines)
