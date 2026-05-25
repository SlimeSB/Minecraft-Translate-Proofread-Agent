"""Vanilla 原版术语词典 — 从 data/vanilla_terms.db 查询 curated 原版术语。

每条术语带 label（软约束，prompt 展示用）和 scope（硬约束，程序预过滤用）。
"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from src.config import RE_FORMAT_SPECIFIER_STRIP, WORD_EXTRACT_PATTERN, VANILLA_TERMS_HEADING, DATA_DIR, VANILLA_TERMS_MAX_SHORT, VANILLA_TERMS_MAX_MIXED
from src.dictionary.protocol import MIXED, SHORT, LookupModeStr, setup_fts
from src.logging import warn
from src.tools.term_validation import STOP_WORDS
from src.tools.version_cmp import version_le

DEFAULT_VT_DB_PATH = DATA_DIR + "/vanilla_terms.db"


class VanillaTermsStore:
    """按需查询 vanilla_terms.db，scope 预过滤，label 标注，multi-en/zh 支持。"""

    lookup_heading = VANILLA_TERMS_HEADING
    default_lookup_mode = MIXED

    def __init__(self, db_path: str = DEFAULT_VT_DB_PATH):
        self._conn: sqlite3.Connection | None = None
        self._loaded = False
        self._db_path = db_path
        self._use_fts = False
        self._label = "VanillaTerms"

    def load(self) -> None:
        if self._loaded:
            return
        db_path = Path(self._db_path)
        if not db_path.exists():
            warn(f"[VanillaTerms] 术语表文件不存在: {db_path}")
            self._loaded = True
            return
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._use_fts = setup_fts(
            self._conn, "terms_fts",
            "en, zh, scope, labels", "terms",
            label="VanillaTerms",
        )
        self._loaded = True

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _scope_matches(self, scope_json: str | None, en_text: str,
                       entry_key: str, version: str | None) -> bool:
        if not scope_json or scope_json == "NULL":
            return True
        try:
            scope: dict[str, str] = json.loads(scope_json)
        except json.JSONDecodeError:
            return True
        for head, pattern in scope.items():
            if head == "key":
                try:
                    if not re.search(pattern, entry_key or ""):
                        return False
                except re.error:
                    return False
            elif head == "version":
                if version is None:
                    return False
                if not version_le(str(version), pattern):
                    return False
            elif head == "en":
                try:
                    if not re.search(pattern, en_text or ""):
                        return False
                except re.error:
                    return False
        return True

    def _parse_json_array(self, raw: str) -> list[str]:
        if not raw:
            return []
        try:
            val = json.loads(raw)
            if isinstance(val, list):
                return [str(v) for v in val]
            return [str(val)]
        except json.JSONDecodeError:
            return [raw.strip('"').strip("'")]

    def _search_fts(self, word: str) -> list[dict[str, Any]]:
        if self._conn is None or not self._use_fts:
            return []
        try:
            rows = self._conn.execute(
                "SELECT rowid, en, zh, scope, labels FROM terms_fts "
                "WHERE terms_fts MATCH ?",
                (f"en:{word}",),
            ).fetchall()
            return [dict(r) for r in rows]
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return []

    def lookup(self, en_text: str, mode: LookupModeStr = MIXED, **kwargs: Any) -> str:
        if not self._loaded:
            self.load()
        if self._conn is None:
            return ""

        query = en_text.strip()
        if not query:
            return ""
        query = RE_FORMAT_SPECIFIER_STRIP.sub(" ", query)
        words = WORD_EXTRACT_PATTERN.findall(query)
        filtered = [w for w in words if len(w) > 1 and w.lower() not in STOP_WORDS]
        if not filtered:
            return ""

        entry_key: str = kwargs.get("entry_key", "")
        version: str | None = kwargs.get("version")

        seen_en: set[str] = set()
        results: list[tuple[str, str, str]] = []

        for word in filtered:
            rows = self._search_fts(word)
            for row in rows:
                en_terms = self._parse_json_array(str(row.get("en", "")))
                zh_terms = self._parse_json_array(str(row.get("zh", "")))
                scope_raw = row.get("scope")
                labels_raw = str(row.get("labels", "[]"))

                if not en_terms or not zh_terms:
                    continue

                scope_str = str(scope_raw) if scope_raw else None
                if not self._scope_matches(scope_str, en_text, entry_key, version):
                    continue

                en_key = " / ".join(en_terms).lower()
                if en_key in seen_en:
                    continue
                seen_en.add(en_key)

                label_str = ""
                try:
                    label_list = json.loads(labels_raw)
                    if isinstance(label_list, list) and label_list:
                        label_str = " [" + ", ".join(label_list) + "]"
                except json.JSONDecodeError:
                    pass

                # 版本敏感标注
                scope_dict: dict[str, str] = {}
                if scope_str and scope_str != "NULL":
                    try:
                        scope_dict = json.loads(scope_str)
                    except json.JSONDecodeError:
                        scope_dict = {}
                version_scope = scope_dict.get("version", "") if isinstance(scope_dict, dict) else ""

                en_display = " / ".join(en_terms)
                zh_display = " / ".join(zh_terms)
                if version_scope:
                    line = f'"{en_display}" → "{zh_display}"[{version_scope}]{label_str}⚠️ 版本敏感译名'
                else:
                    line = f'"{en_display}" → "{zh_display}"{label_str}'
                results.append((en_display.lower(), line, labels_raw))

        if not results:
            return ""

        max_total = kwargs.get("max_total", VANILLA_TERMS_MAX_SHORT) if mode == SHORT else VANILLA_TERMS_MAX_MIXED
        results = results[:max_total]
        return "\n".join(r[1] for r in results)
