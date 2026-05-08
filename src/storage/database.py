"""PipelineDB —— 单一 SQLite 数据库，替代所有中间 JSON 文件。

用法:
    db = PipelineDB(ctx.output_dir / "pipeline.db")
    db.save_alignment(ctx.alignment)
    db.save_verdicts(ctx.format_verdicts, "format")
    db.close()
"""
import json
import sqlite3
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════
# Schema
# ═══════════════════════════════════════════════════════════

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS alignment (
    key     TEXT PRIMARY KEY,
    en      TEXT DEFAULT '',
    zh      TEXT DEFAULT '',
    format  TEXT DEFAULT '',
    namespace TEXT DEFAULT '',
    old_en  TEXT DEFAULT '',
    old_zh  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS glossary (
    en TEXT PRIMARY KEY,
    zh TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verdicts (
    key         TEXT NOT NULL,
    phase       TEXT NOT NULL,
    en_current  TEXT DEFAULT '',
    zh_current  TEXT DEFAULT '',
    verdict     TEXT DEFAULT '',
    suggestion  TEXT DEFAULT '',
    reason      TEXT DEFAULT '',
    source      TEXT DEFAULT '',
    namespace   TEXT DEFAULT '',
    filtered    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_verdicts_key_phase ON verdicts(key, phase);
CREATE INDEX IF NOT EXISTS ix_verdicts_phase ON verdicts(phase);
CREATE INDEX IF NOT EXISTS ix_verdicts_ns ON verdicts(namespace);
CREATE INDEX IF NOT EXISTS ix_verdicts_filtered ON verdicts(filtered);

CREATE TABLE IF NOT EXISTS fuzzy_results (
    key        TEXT NOT NULL,
    similarity REAL,
    ref_key    TEXT,
    ref_en     TEXT,
    ref_zh     TEXT,
    PRIMARY KEY (key, ref_key)
);

CREATE TABLE IF NOT EXISTS filter_cache (
    cache_key      TEXT PRIMARY KEY,
    action         TEXT NOT NULL,
    cleaned_reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# ═══════════════════════════════════════════════════════════
# PipelineDB
# ═══════════════════════════════════════════════════════════


class PipelineDB:
    """与 `ctx.output_dir / "pipeline.db"` 绑定的 SQLite 数据库。"""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── Alignment ──────────────────────────────────────

    def save_alignment(self, alignment: dict) -> None:
        entries = alignment.get("matched_entries", [])
        self._conn.execute("DELETE FROM alignment")
        for e in entries:
            chg = e.get("_change") or {}
            self._conn.execute(
                "INSERT INTO alignment (key,en,zh,format,namespace,old_en,old_zh) "
                "VALUES (?,?,?,?,?,?,?)",
                (e["key"], e.get("en", ""), e.get("zh", ""),
                 e.get("format", ""), e.get("namespace", ""),
                 chg.get("old_en", ""), chg.get("old_zh", "")))
        self._conn.commit()

    def load_alignment(self) -> dict:
        rows = self._conn.execute("SELECT * FROM alignment").fetchall()
        matched = []
        for r in rows:
            matched.append({
                "key": r["key"], "en": r["en"], "zh": r["zh"],
                "format": r["format"], "namespace": r["namespace"],
            })
        return {"matched_entries": matched, "stats": {"matched": len(matched)}}

    # ── Glossary ───────────────────────────────────────

    def save_glossary(self, glossary: list[dict]) -> None:
        self._conn.execute("DELETE FROM glossary")
        for g in glossary:
            self._conn.execute("INSERT INTO glossary (en,zh) VALUES (?,?)",
                               (g.get("en", ""), g.get("zh", "")))
        self._conn.commit()

    def load_glossary(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM glossary").fetchall()
        return [{"en": r["en"], "zh": r["zh"]} for r in rows]

    # ── Verdicts ───────────────────────────────────────

    def save_verdicts(self, verdicts: list[dict], phase: str) -> None:
        """按 phase 保存判决（'format' / 'terminology' / 'llm' / 'merged'）。"""
        self._conn.execute("DELETE FROM verdicts WHERE phase=?", (phase,))
        for v in verdicts:
            def _s(key: str, default: str = "") -> str:
                val = v.get(key, default)
                if isinstance(val, str):
                    return val
                if isinstance(val, dict):
                    return val.get("zh", "") or val.get("text", "") or val.get("value", "") or str(val)
                return str(val) if val else default
            self._conn.execute(
                "INSERT INTO verdicts (key,phase,en_current,zh_current,verdict,suggestion,reason,source,namespace) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (_s("key"), phase,
                 _s("en_current"), _s("zh_current"),
                 _s("verdict"), _s("suggestion"),
                 _s("reason"), _s("source"),
                 _s("namespace")))
        self._conn.commit()

    def load_verdicts(self, phase: str | None = None,
                      namespace: str | None = None,
                      filtered: int | None = 0) -> list[dict]:
        """加载判决，可按 phase / namespace / filtered 筛选。
        filtered=0 → 仅未过滤（默认），None → 全部。
        """
        sql = "SELECT * FROM verdicts WHERE 1=1"
        params: list[Any] = []
        if phase is not None:
            sql += " AND phase=?"
            params.append(phase)
        if namespace is not None:
            sql += " AND namespace=?"
            params.append(namespace)
        if filtered is not None:
            sql += " AND filtered=?"
            params.append(filtered)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def set_filtered(self, key: str, verdict: str, reason: str) -> None:
        """标记 verdict 为已过滤，同时更新判决（PASS 表示驳回）。"""
        if reason:
            self._conn.execute(
                "UPDATE verdicts SET filtered=1, verdict=?, reason=? WHERE key=? AND phase='merged'",
                (verdict, reason, key))
        else:
            self._conn.execute(
                "UPDATE verdicts SET filtered=1, verdict=? WHERE key=? AND phase='merged'",
                (verdict, key))
        self._conn.commit()

    def set_merged_reason(self, key: str, reason: str) -> None:
        self._conn.execute(
            "UPDATE verdicts SET reason=? WHERE key=? AND phase='merged'",
            (reason, key))
        self._conn.commit()

    def get_merged_stats(self) -> dict[str, int]:
        # 已过滤的 verdict（filtered=1）
        total = self._conn.execute(
            "SELECT COUNT(DISTINCT key) FROM verdicts WHERE filtered=1").fetchone()[0]
        issues = self._conn.execute(
            "SELECT COUNT(DISTINCT key) FROM verdicts WHERE filtered=1 AND verdict != 'PASS'").fetchone()[0]

        def _cnt(verdict_pat: str) -> int:
            return self._conn.execute(
                "SELECT COUNT(DISTINCT key) FROM verdicts "
                "WHERE filtered=1 AND verdict LIKE ?",
                (f"%{verdict_pat}%",)).fetchone()[0]

        return {
            "total": total,
            "PASS": total - issues,
            "⚠️ SUGGEST": _cnt("SUGGEST"),
            "❌ FAIL": _cnt("FAIL"),
            "🔶 REVIEW": _cnt("REVIEW"),
        }

    # ── Fuzzy Results ──────────────────────────────────

    def save_fuzzy_results(self, fm: dict[str, list[dict]]) -> None:
        self._conn.execute("DELETE FROM fuzzy_results")
        for key, items in fm.items():
            for it in items:
                self._conn.execute(
                    "INSERT INTO fuzzy_results (key,similarity,ref_key,ref_en,ref_zh) "
                    "VALUES (?,?,?,?,?)",
                    (key, it.get("similarity", 0), it.get("key", ""),
                     it.get("en", ""), it.get("zh", "")))
        self._conn.commit()

    def load_fuzzy_results(self) -> dict[str, list[dict]]:
        rows = self._conn.execute("SELECT * FROM fuzzy_results").fetchall()
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r["key"], []).append({
                "similarity": r["similarity"], "key": r["ref_key"],
                "en": r["ref_en"], "zh": r["ref_zh"],
            })
        return out

    # ── Filter Cache ───────────────────────────────────

    def lookup_filter_cache(self, cache_key: str) -> tuple[str, str] | None:
        row = self._conn.execute(
            "SELECT action,cleaned_reason FROM filter_cache WHERE cache_key=?",
            (cache_key,)).fetchone()
        if row:
            return row["action"], row["cleaned_reason"]
        return None

    def store_filter_cache(self, cache_key: str, action: str, reason: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO filter_cache (cache_key,action,cleaned_reason) "
            "VALUES (?,?,?)", (cache_key, action, reason))

    def filter_cache_size(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM filter_cache").fetchone()[0]

    def commit_filter_cache(self) -> None:
        self._conn.commit()

    # ── Meta ───────────────────────────────────────────

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta (key,value) VALUES (?,?)",
                           (key, value))
        self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "key": row["key"],
        "en_current": row["en_current"],
        "zh_current": row["zh_current"],
        "verdict": row["verdict"],
        "suggestion": row["suggestion"],
        "reason": row["reason"],
        "source": row["source"],
        "namespace": row["namespace"],
    }
