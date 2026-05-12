"""Minecraft 原版翻译词典 — 从 data/Minecraft.db 查询原版翻译参考。"""

import sqlite3
from pathlib import Path
from typing import Any

from src.logging import warn
from src.dictionary.protocol import LookupMode
from src.tools.version_utils import parse_version
from src.tools.term_validation import STOP_WORDS

DEFAULT_DB_PATH = "data/Minecraft.db"


class MinecraftDictStore:
    """按需查询 Minecraft 原版翻译，SQLite FTS5 全文搜索。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._conn: sqlite3.Connection | None = None
        self._loaded = False
        self._db_path = db_path
        self._use_fts = False

    def load(self) -> None:
        if self._loaded:
            return
        db_path = Path(self._db_path)
        if not db_path.exists():
            self._loaded = True
            return
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_vanilla_keys_en_us "
                "ON vanilla_keys(en_us)"
            )
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vanilla_keys_fts "
                "USING fts5(en_us, zh_cn, key, version_start, version_end, "
                "changes, content=vanilla_keys, content_rowid=rowid)"
            )
            self._conn.execute(
                "INSERT INTO vanilla_keys_fts(vanilla_keys_fts) VALUES('rebuild')"
            )
            self._use_fts = True
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            warn(f"[MinecraftDict] FTS5 创建失败 ({e})，降级为 LIKE 查询")
            self._use_fts = False
            try:
                self._conn.execute(
                    "DROP TABLE IF EXISTS vanilla_keys_fts"
                )
            except sqlite3.OperationalError:
                pass
        self._loaded = True

    def _search_fts(self, term: str) -> list[dict[str, Any]]:
        if self._conn is None:
            return []
        try:
            rows = self._conn.execute(
                "SELECT key, en_us, zh_cn, version_start, version_end, changes "
                "FROM vanilla_keys_fts WHERE vanilla_keys_fts MATCH ?",
                (term,),
            ).fetchall()
            return [dict(r) for r in rows]
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            self._use_fts = False
            return []

    def _search_like(self, term: str) -> list[dict[str, Any]]:
        if self._conn is None:
            return []
        try:
            rows = self._conn.execute(
                "SELECT key, en_us, zh_cn, version_start, version_end, changes "
                "FROM vanilla_keys WHERE LOWER(en_us) LIKE ?",
                (f"%{term.lower()}%",),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def _search_by_key(self, key: str) -> list[dict[str, Any]]:
        if self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT key, en_us, zh_cn, version_start, version_end, changes "
            "FROM vanilla_keys WHERE key=? ORDER BY version_start",
            (key,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _in_version_range(self, version: str, start: str, end: str) -> bool:
        v = parse_version(version)
        s = parse_version(start)
        e = parse_version(end)
        return s <= v <= e

    def _version_key(self, row: dict[str, Any]) -> tuple[int, ...]:
        return parse_version(row.get("version_end", "0.0.0"))

    def lookup(self, en_text: str, mode: str = LookupMode.MIXED, **kwargs: Any) -> str:
        if not self._loaded:
            self.load()
        if self._conn is None:
            return ""

        query = en_text.strip().lower()
        if not query:
            return ""
        words = query.split()
        filtered = [w for w in words if w not in STOP_WORDS]
        if not filtered:
            return ""
        if len(filtered) == 1 and filtered[0] in STOP_WORDS:
            return ""

        search_term = " OR ".join(f'"{w}"' for w in filtered) if self._use_fts else " ".join(filtered)

        rows = self._search_fts(search_term) if self._use_fts else self._search_like(search_term)
        if not rows:
            return ""

        target_version: str | None = kwargs.get("target_version")

        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            k = r["key"]
            groups.setdefault(k, []).append(r)

        max_total = 5
        changes1_keys: set[str] = set()
        normal_groups: dict[str, list[dict[str, Any]]] = {}
        for k, entries in groups.items():
            changes_val = entries[0].get("changes", 0)
            if changes_val == 1:
                changes1_keys.add(k)
            else:
                normal_groups[k] = entries

        changes1_rows: list[dict[str, Any]] = []
        for k in changes1_keys:
            full = self._search_by_key(k)
            changes1_rows.extend(full)

        normal_picked: list[dict[str, Any]] = []
        for k, entries in normal_groups.items():
            best = min(entries, key=lambda e: abs(len(e.get("en_us", "")) - self._target_len(entries)))
            normal_picked.append(best)

        if mode == LookupMode.SHORT:
            normal_picked.sort(key=lambda e: len(e.get("en_us", "")))
            normal_picked = normal_picked[:max_total]
        else:
            if normal_picked:
                longest = max(normal_picked, key=lambda e: len(e.get("en_us", "")))
                rest = [e for e in normal_picked if e is not longest]
                rest.sort(key=lambda e: len(e.get("en_us", "")))
                rest = rest[:max_total - 1]
                normal_picked = [longest] + rest

        has_sensitive = bool(changes1_rows)

        lines: list[str] = []

        def escape_newlines(s: str) -> str:
            return s.replace("\n", "\\n")

        if not has_sensitive:
            for r in normal_picked:
                lines.append(
                    f'"{escape_newlines(r["en_us"])}" -> "{escape_newlines(r["zh_cn"])}" [{r["version_start"]}-{r["version_end"]}]'
                )
        elif normal_picked:
            shortest = min(normal_picked, key=lambda e: len(e.get("en_us", "")))
            lines.append(
                f'"{escape_newlines(shortest["en_us"])}" -> "{escape_newlines(shortest["zh_cn"])}" [{shortest["version_start"]}-{shortest["version_end"]}]'
            )

        if changes1_rows:
            by_key: dict[str, list[dict[str, Any]]] = {}
            for r in changes1_rows:
                by_key.setdefault(r["key"], []).append(r)

            sens_lines: list[str] = []
            for entries in by_key.values():
                if len(sens_lines) >= max_total:
                    break
                entries.sort(key=self._version_key, reverse=True)

                def sort_key(r: dict[str, Any]) -> tuple[int, int]:
                    if target_version and self._in_version_range(target_version, r["version_start"], r["version_end"]):
                        return (0, 0)
                    return (1, 0)

                entries.sort(key=sort_key)

                for i, r in enumerate(entries):
                    if len(sens_lines) >= max_total:
                        break
                    prefix = "- " if i else ""
                    sens_lines.append(
                        f'{prefix}"{escape_newlines(r["en_us"])}" -> "{escape_newlines(r["zh_cn"])}" [{r["version_start"]}-{r["version_end"]}]'
                    )
            lines.extend(sens_lines)

        if not lines:
            return ""

        body = "\n".join(lines)
        header = "原版词典："
        if has_sensitive:
            header += "版本敏感译名（不同版本存在差异）"
        return header + "\n" + body

    def _target_len(self, entries: list[dict[str, Any]]) -> int:
        if not entries:
            return 0
        avg = sum(len(e.get("en_us", "")) for e in entries) // len(entries)
        return avg

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
