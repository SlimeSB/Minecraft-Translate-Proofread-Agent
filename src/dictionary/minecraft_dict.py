"""Minecraft 原版翻译词典 — 从 data/Minecraft.db 查询原版翻译参考。"""

import sqlite3
from pathlib import Path
from typing import Any

from src.logging import warn
from src.config import RE_FORMAT_SPECIFIER_STRIP, WORD_EXTRACT_PATTERN, VD_PER_WORD_TRIGGERS, VD_FUZZY_TRIGGERS, VD_WORD_COUNT_THRESHOLD
from src.dictionary.protocol import LookupMode
from src.tools.fuzzy_search import calc_similarity
from src.tools.version_utils import parse_version
from src.tools.term_validation import STOP_WORDS

VD_SIMILARITY_THRESHOLD: float = 60.0
VD_MAX_LONG_WORDS: int = 30
VD_MAX_SHORT_WORDS: int = 10

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
        self._conn.execute("PRAGMA busy_timeout = 5000")
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
                "FROM vanilla_keys_fts WHERE vanilla_keys_fts MATCH ? ORDER BY rank",
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

    def _format_rows(self, rows: list[dict[str, Any]], mode: str = LookupMode.MIXED, max_total: int = 5, target_version: str | None = None, show_sim: bool = False) -> tuple[list[str], bool]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            k = r["key"]
            groups.setdefault(k, []).append(r)

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
                long_candidates = [e for e in normal_picked if len((e.get("en_us", "") or "").split()) <= VD_MAX_LONG_WORDS]
                if long_candidates:
                    longest = max(long_candidates, key=lambda e: len((e.get("en_us", "") or "").split()))
                else:
                    longest = None
                rest = [e for e in normal_picked if e is not longest]
                rest = [e for e in rest if len((e.get("en_us", "") or "").split()) <= VD_MAX_SHORT_WORDS]
                rest.sort(key=lambda e: len((e.get("en_us", "") or "").split()))
                rest = rest[:max_total - (1 if longest else 0)]
                normal_picked = ([longest] if longest else []) + rest

        has_sensitive = bool(changes1_rows)

        lines: list[str] = []

        def escape_newlines(s: str) -> str:
            return s.replace("\n", "\\n")

        def fmt_entry(r: dict[str, Any], prefix: str = "") -> str:
            sim_part = f"sim={r['_sim']:.1f}% | " if show_sim and "_sim" in r else ""
            return f'{sim_part}{prefix}"{escape_newlines(r["en_us"])}" -> "{escape_newlines(r["zh_cn"])}" [{r["version_start"]}-{r["version_end"]}]'

        longest_normal: dict[str, Any] | None = None
        shortest_normal: dict[str, Any] | None = None

        if not has_sensitive:
            for r in normal_picked:
                lines.append(fmt_entry(r))
        elif normal_picked:
            long_candidates_norm = [e for e in normal_picked if len((e.get("en_us", "") or "").split()) <= VD_MAX_LONG_WORDS]
            if long_candidates_norm:
                longest_normal = max(long_candidates_norm, key=lambda e: len((e.get("en_us", "") or "").split()))
            else:
                longest_normal = None
            short_candidates_norm = [e for e in normal_picked if len((e.get("en_us", "") or "").split()) <= VD_MAX_SHORT_WORDS]
            if short_candidates_norm:
                shortest_normal = min(short_candidates_norm, key=lambda e: len((e.get("en_us", "") or "").split()))
            else:
                shortest_normal = None
            if longest_normal and shortest_normal and longest_normal is shortest_normal:
                shortest_normal = None

        if changes1_rows:
            by_key: dict[str, list[dict[str, Any]]] = {}
            for r in changes1_rows:
                by_key.setdefault(r["key"], []).append(r)

            def _group_max_len(entries: list[dict[str, Any]]) -> int:
                return max(len(e.get("en_us", "")) for e in entries)

            sorted_groups = sorted(by_key.values(), key=_group_max_len, reverse=True)

            reserved = 0
            if longest_normal is not None:
                reserved += 1
            if shortest_normal is not None:
                reserved += 1
            max_sensitive = max(0, max_total - reserved)

            sens_lines: list[str] = []
            sens_groups = 0
            for entries in sorted_groups:
                if sens_groups >= max_sensitive:
                    break
                entries = [r for r in entries if len((r.get("en_us", "") or "").split()) <= VD_MAX_LONG_WORDS]
                if not entries:
                    continue
                sens_groups += 1
                entries.sort(key=self._version_key, reverse=True)

                def sort_key(r: dict[str, Any]) -> tuple[int, int]:
                    if target_version and self._in_version_range(target_version, r["version_start"], r["version_end"]):
                        return (0, 0)
                    return (1, 0)

                entries.sort(key=sort_key)

                for i, r in enumerate(entries):
                    prefix = "- " if i else ""
                    sens_lines.append(fmt_entry(r, prefix))

            if longest_normal is not None:
                lines.append(fmt_entry(longest_normal))
            lines.extend(sens_lines)
            if shortest_normal is not None and len(lines) < max_total:
                lines.append(fmt_entry(shortest_normal))

        return lines, has_sensitive

    def _lookup_single_term(self, term: str, mode: str = LookupMode.MIXED, max_total: int = 5,
                           target_version: str | None = None,
                           seen_keys: set[str] | None = None) -> tuple[list[str], bool]:
        if self._conn is None:
            return [], False

        search_term = f'en_us:{term}*' if self._use_fts else term
        rows = self._search_fts(search_term) if self._use_fts else self._search_like(search_term)
        if not rows:
            return [], False

        if seen_keys is not None:
            rows = [r for r in rows if r["key"] not in seen_keys]
            if not rows:
                return [], False

        if seen_keys is not None:
            for r in rows:
                seen_keys.add(r["key"])

        return self._format_rows(rows, mode, max_total, target_version)

    def lookup(self, en_text: str, mode: str = LookupMode.MIXED, **kwargs: Any) -> str:
        if not self._loaded:
            self.load()
        if self._conn is None:
            return ""

        query = en_text.strip().lower()
        if not query:
            return ""
        query = RE_FORMAT_SPECIFIER_STRIP.sub(" ", query)
        words = WORD_EXTRACT_PATTERN.findall(query)
        filtered = [w for w in words if len(w) > 1 and w not in STOP_WORDS]
        if not filtered:
            return ""

        target_version: str | None = kwargs.get("target_version")
        entry_key: str = kwargs.get("entry_key", "")
        word_set = set(filtered)
        key_has_per_word = any(t in entry_key for t in VD_PER_WORD_TRIGGERS)
        key_has_fuzzy = any(t in entry_key for t in VD_FUZZY_TRIGGERS)
        if not key_has_per_word and (key_has_fuzzy or word_set & VD_FUZZY_TRIGGERS or len(words) > VD_WORD_COUNT_THRESHOLD):
            search_term = " OR ".join(f'en_us:{w}*' for w in filtered) if self._use_fts else " ".join(filtered)
            rows = self._search_fts(search_term) if self._use_fts else self._search_like(search_term)
            if not rows:
                return ""
            for r in rows:
                r["_sim"] = calc_similarity(query, (r["en_us"] or "").lower())
            if len(filtered) > VD_WORD_COUNT_THRESHOLD:
                rows = [r for r in rows if r["_sim"] >= VD_SIMILARITY_THRESHOLD]
                if not rows:
                    return ""
            lines, has_sensitive = self._format_rows(rows, mode, 5, target_version, show_sim=True)
            if not lines:
                return ""
            return self._make_result(lines, has_sensitive, sub_label="模糊匹配：")

        # 默认 / block&item 强制 → 逐词分组
        any_sensitive = False
        all_lines: list[str] = []
        seen_keys: set[str] = set()
        for word in filtered:
            lines, has_sensitive = self._lookup_single_term(word, mode, 5, target_version, seen_keys=seen_keys)
            if has_sensitive:
                any_sensitive = True
            if lines:
                all_lines.append(f"{word.capitalize()}：")
                all_lines.extend(lines)
                all_lines.append("")

        if not all_lines:
            return ""

        if all_lines and all_lines[-1] == "":
            all_lines.pop()

        return self._make_result(all_lines, any_sensitive)

    def _make_result(self, lines: list[str], has_sensitive: bool, sub_label: str = "") -> str:
        body = "\n".join(lines)
        header = "原版词典："
        if has_sensitive:
            header += "存在版本敏感译名，不同版本存在差异。"
        if sub_label:
            header += "\n" + sub_label
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
