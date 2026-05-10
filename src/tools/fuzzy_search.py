"""
轻量模糊搜索工具：SQLite FTS5 全文索引 + 编辑距离精排。
用于 translation-reviewer agent 的翻译记忆匹配。

用法:
    python fuzzy_search.py --query "待翻译文本" --en en_us.json --zh zh_cn.json [--threshold 50] [--top 5]

输出:
    JSON: { "similar_lines": [{ "similarity": 85.5, "key": "...", "en": "...", "zh": "..." }, ...] }
"""
import json
import sqlite3
import sys
from src import config as cfg
from src.models import FuzzyResultDict


# ═══════════════════════════════════════════════════════════
# 编辑距离（仅对 FTS 候选做精排）
# ═══════════════════════════════════════════════════════════

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def calc_similarity(query: str, line: str) -> float:
    if not query or not line:
        return 0.0
    dist = levenshtein_distance(query, line)
    max_len = max(len(query), len(line))
    return round(100 * (1 - dist / max_len), 2)


# ═══════════════════════════════════════════════════════════
# SQLite FTS5 引擎
# ═══════════════════════════════════════════════════════════

class TranslationDB:
    """在内存 SQLite FTS5 中索引 en_us/zh_cn 对，提供快速模糊搜索。"""

    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=OFF")
        self.conn.execute("PRAGMA synchronous=OFF")
        self._initialized = False

    def build(self, en_entries: dict[str, str], zh_entries: dict[str, str]) -> None:
        """构建 FTS5 索引。"""
        self.conn.execute("DROP TABLE IF EXISTS entries")
        self.conn.execute("DROP TABLE IF EXISTS entries_fts")
        self.conn.execute(
            "CREATE TABLE entries (key TEXT PRIMARY KEY, en TEXT, zh TEXT)"
        )
        self.conn.execute(
            "CREATE VIRTUAL TABLE entries_fts USING fts5(key, en, zh, content='entries', content_rowid='rowid')"
        )
        cur = self.conn.cursor()
        cur.execute("BEGIN")
        for key, en_val in en_entries.items():
            zh_val = zh_entries.get(key, "")
            cur.execute(
                "INSERT INTO entries (key, en, zh) VALUES (?, ?, ?)",
                (key, en_val or "", zh_val or ""),
            )
        cur.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
        self.conn.commit()
        self._initialized = True

    def search(
        self,
        query: str,
        zh_entries: dict[str, str] | None = None,
        top_n: int = 5,
        threshold: float = 50.0,
    ) -> list[FuzzyResultDict]:
        """
        模糊搜索。先用 FTS5 token 前缀匹配召回候选，再用编辑距离精排。
        """
        if not self._initialized or not query.strip():
            return []

        # FTS5 前缀查询：每个 token 后加 *
        tokens = []
        for t in query.split():
            t_clean = "".join(c for c in t if c.isalnum())
            if len(t_clean) >= 2:
                tokens.append(t_clean + "*")
        if not tokens:
            return []

        fts_query = " OR ".join(tokens)
        fts_col = "en"

        try:
            recall_mult = cfg.get("fts_recall_multiplier", 10)
            recall_min = cfg.get("fts_recall_min", 50)
            cur = self.conn.execute(
                f"SELECT key, en, zh FROM entries_fts WHERE entries_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, max(top_n * recall_mult, recall_min)),
            )
            candidates = [(row[0], row[1], row[2]) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return []

        # 编辑距离精排
        results: list[FuzzyResultDict] = []
        for key, en_text, zh_text in candidates:
            sim = calc_similarity(query, en_text or "")
            if sim >= threshold:
                results.append({
                    "similarity": sim,
                    "key": key,
                    "en": en_text or "",
                    "zh": zh_text or (zh_entries.get(key, "(无翻译)") if zh_entries else ""),
                })
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_n]


# ═══════════════════════════════════════════════════════════
# 单例（复用 FTS 索引，避免每次查询重建）
# ═══════════════════════════════════════════════════════════

# Module-level singleton — intentional: caches SQLite DB by key set to avoid rebuild on repeated calls
_db_instance: TranslationDB | None = None
_db_key_set: frozenset[str] | None = None


def _get_db(en_entries: dict[str, str], zh_entries: dict[str, str]) -> TranslationDB:
    global _db_instance, _db_key_set
    current_keys = frozenset(en_entries.keys())
    if _db_instance is None or _db_key_set != current_keys:
        _db_instance = TranslationDB()
        _db_instance.build(en_entries, zh_entries)
        _db_key_set = current_keys
    return _db_instance


def fuzzy_search_lines(
    query: str,
    en_entries: dict[str, str],
    zh_entries: dict[str, str],
    top_n: int = 5,
    threshold: float = 50.0,
) -> list[FuzzyResultDict]:
    """在翻译记忆库中模糊搜索（保持旧 API 兼容）。"""
    db = _get_db(en_entries, zh_entries)
    return db.search(query, zh_entries, top_n, threshold)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="在翻译记忆库中模糊搜索相似翻译")
    parser.add_argument("--query", required=True, help="待查找的英文原文")
    parser.add_argument("--en", required=True, help="en_us.json 路径")
    parser.add_argument("--zh", required=True, help="zh_cn.json 路径")
    parser.add_argument("--threshold", type=float, default=50.0, help="相似度阈值 (0-100)，默认50")
    parser.add_argument("--top", type=int, default=5, help="返回最相似的前N条，默认5")

    args = parser.parse_args()

    try:
        en_entries = load_json(args.en)
        zh_entries = load_json(args.zh)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    matches = fuzzy_search_lines(
        query=args.query,
        en_entries=en_entries,
        zh_entries=zh_entries,
        top_n=args.top,
        threshold=args.threshold,
    )
    print(json.dumps({"similar_lines": matches}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

