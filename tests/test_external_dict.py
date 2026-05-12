"""测试 ExternalDictStore — 索引/FTS 查询/词形缓存/去重/截断/边界。"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.dictionary.external import ExternalDictStore


def _create_test_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE dict (
            ORIGIN_NAME TEXT,
            TRANS_NAME TEXT,
            MODID TEXT
        )
    """)
    conn.commit()
    conn.close()


def _insert(conn: sqlite3.Connection, origin: str, trans: str, modid: str) -> None:
    conn.execute(
        "INSERT INTO dict (ORIGIN_NAME, TRANS_NAME, MODID) VALUES (?, ?, ?)",
        (origin, trans, modid),
    )


class TestExternalDictStore(unittest.TestCase):

    def _make_store(self, use_fts: bool = True):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        _create_test_db(path)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        # Manually create FTS if needed so load() picks it up
        if use_fts:
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS dict_fts "
                    "USING fts5(ORIGIN_NAME, TRANS_NAME, MODID, content=dict, content_rowid=rowid)"
                )
                conn.execute("INSERT INTO dict_fts(dict_fts) VALUES('rebuild')")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        return path, conn, ExternalDictStore(db_path=path)

    # ———— 边界 ————

    def test_db_not_exists(self):
        store = ExternalDictStore(db_path="/nonexistent/path_xyz.db")
        store.load()
        self.assertEqual(store.lookup("stone"), "")

    def test_empty_query(self):
        path, conn, store = self._make_store()
        try:
            store.load()
            self.assertEqual(store.lookup(""), "")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    def test_empty_result(self):
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Stone", "石头", "minecraft")
            conn.commit()
            store.load()
            self.assertEqual(store.lookup("zzzznotexist"), "")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # ———— 基本查询 ————

    def test_basic_lookup_fts(self):
        path, conn, store = self._make_store(use_fts=True)
        try:
            _insert(conn, "Stone", "石头", "minecraft")
            conn.commit()
            store.load()
            result = store.lookup("stone")
            self.assertIn("外部词典", result)
            self.assertIn("Stone -> 石头", result)
            self.assertIn("minecraft", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    def test_basic_lookup_index(self):
        path, conn, store = self._make_store(use_fts=False)
        try:
            _insert(conn, "Stone", "石头", "minecraft")
            conn.commit()
            store.load()
            result = store.lookup("stone")
            self.assertIn("外部词典", result)
            self.assertIn("Stone -> 石头", result)
            self.assertIn("minecraft", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # ———— 去重 (origin.lower(), zh) ————

    def test_dedup_same_origin_same_zh_merges_modids(self):
        """相同 ORIGIN_NAME 且相同 TRANS_NAME → 合并 modid。"""
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Stone", "石头", "mod_a")
            _insert(conn, "Stone", "石头", "mod_b")
            conn.commit()
            store.load()
            result = store.lookup("stone")
            lines = [l for l in result.split("\n") if " -> " in l]
            self.assertEqual(len(lines), 1)
            self.assertIn("mod_a", lines[0])
            self.assertIn("mod_b", lines[0])
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    def test_dedup_different_zh_kept_separate(self):
        """相同 ORIGIN_NAME 但不同译文 → 分别保留。"""
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Stone", "石头", "mod_a")
            _insert(conn, "Stone", "岩石", "mod_b")
            conn.commit()
            store.load()
            result = store.lookup("stone")
            lines = [l for l in result.split("\n") if " -> " in l]
            self.assertEqual(len(lines), 2)
            self.assertIn("石头", result)
            self.assertIn("岩石", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    def test_dedup_different_origin_same_zh_kept_separate(self):
        """不同 ORIGIN_NAME 相同译文 → 分别保留。"""
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Stone", "石头", "mod_a")
            _insert(conn, "Rock", "石头", "mod_b")
            conn.commit()
            store.load()
            result = store.lookup("stone rock")
            lines = [l for l in result.split("\n") if " -> " in l]
            self.assertEqual(len(lines), 2)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    def test_output_shows_origin_not_matched_word(self):
        """输出显示 DB 的 ORIGIN_NAME 而非查询时匹配到的词。"""
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Smooth Stone", "平滑石头", "minecraft")
            conn.commit()
            store.load()
            result = store.lookup("smooth")
            self.assertIn("Smooth Stone", result)
            self.assertNotIn("smooth ->", result.lower())
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # ———— 词形缓存 (lemma) ————

    def test_lemma_fallback(self):
        """查询词不在 DB 中但词形缓存有映射 → 用 canonical 再查。"""
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Stones", "石头们", "mod_x")
            conn.commit()
            store._lemma_map = {"stone": "Stones"}
            store.load()
            result = store.lookup("stone")
            self.assertIn("Stones -> 石头们", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    def test_lemma_no_loop_when_canon_equals_word(self):
        """canon.lower() == w_lower 时不重复查询。"""
        path, conn, store = self._make_store()
        try:
            _insert(conn, "stone", "石头", "mod_x")
            conn.commit()
            store._lemma_map = {"stone": "stone"}
            store.load()
            result = store.lookup("stone")
            self.assertIn("stone -> 石头", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # ———— 停用词 ————

    def test_stop_word_returns_empty(self):
        path, conn, store = self._make_store()
        try:
            _insert(conn, "the", "定冠词", "mod_x")
            conn.commit()
            store.load()
            self.assertEqual(store.lookup("the"), "")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    def test_stop_word_filtered_from_text(self):
        """含停用词的文本中，停用词被过滤，剩余词正常查询。"""
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Stone", "石头", "minecraft")
            conn.commit()
            store.load()
            result = store.lookup("the stone")
            self.assertIn("Stone -> 石头", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # ———— 截断 ————

    def test_max_groups(self):
        path, conn, store = self._make_store()
        try:
            words = ["Apple", "Banana", "Cherry", "Durian", "Elderberry", "Fig"]
            for i, w in enumerate(words):
                _insert(conn, w, f"翻译{i}", "mod_a")
            conn.commit()
            store.load()
            result = store.lookup(" ".join(words), max_groups=3)
            lines = [l for l in result.split("\n") if " -> " in l]
            self.assertEqual(len(lines), 3)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    def test_max_modids(self):
        path, conn, store = self._make_store()
        try:
            for i in range(8):
                _insert(conn, "Stone", "石头", f"mod_{i}")
            conn.commit()
            store.load()
            result = store.lookup("stone", max_modids=3)
            self.assertIn("+5", result)
            modids_in_line = result.count("mod_")
            self.assertEqual(modids_in_line, 3)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # ———— 排序（按 modid 数量降序） ————

    def test_sort_by_modid_count_desc(self):
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Popular", "流行", "a")
            _insert(conn, "Popular", "流行", "b")
            _insert(conn, "Popular", "流行", "c")
            _insert(conn, "Rare", "稀有", "x")
            conn.commit()
            store.load()
            result = store.lookup("Popular Rare")
            lines = [l for l in result.split("\n") if " -> " in l]
            self.assertIn("Popular", lines[0])
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # ———— close ————

    def test_close(self):
        path, conn, store = self._make_store()
        store.load()
        store.close()
        self.assertIsNone(store._conn)
        conn.close()
        Path(path).unlink(missing_ok=True)

    # ———— FTS 降级 ————

    def test_fts_fallback_to_index(self):
        """FTS 查询异常时自动降级为索引查询。"""
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Stone", "石头", "minecraft")
            _insert(conn, "Wood", "木头", "minecraft")
            conn.commit()
            store.load()
            self.assertTrue(store._use_fts)
            store.close()
            conn.execute("DROP TABLE IF EXISTS dict_fts")
            conn.commit()
            # 重连 — _loaded 仍为 True，跳过 load()
            store._conn = sqlite3.connect(path)
            store._conn.row_factory = sqlite3.Row
            store._use_fts = True
            result = store.lookup("stone wood")
            self.assertFalse(store._use_fts)
            self.assertIn("木头", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # short 模式按原文长度升序排序
    def test_short_mode_sorts_by_length(self):
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Long Original Text", "长文本", "mod_a")
            _insert(conn, "Short", "短文本", "mod_a")
            _insert(conn, "Medium Text", "中文本", "mod_a")
            conn.commit()
            store.load()
            result = store.lookup("Long Original Text Short Medium Text", mode="short")
            lines = [l for l in result.split("\n") if " -> " in l]
            self.assertEqual(len(lines), 3)
            self.assertIn("Short", lines[0], "短模式最短原文应排第一")
            self.assertIn("Long Original Text", lines[2], "短模式最长原文应排最后")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # mixed 模式保持 modid 数量降序（不受 short 影响）
    def test_mixed_mode_keeps_modid_sort(self):
        path, conn, store = self._make_store()
        try:
            _insert(conn, "Rare Term", "稀有", "mod_x")
            _insert(conn, "Popular Term", "热门", "mod_a")
            _insert(conn, "Popular Term", "热门", "mod_b")
            _insert(conn, "Popular Term", "热门", "mod_c")
            conn.commit()
            store.load()
            result = store.lookup("Rare Term Popular Term", mode="mixed")
            lines = [l for l in result.split("\n") if " -> " in l]
            self.assertIn("Popular Term", lines[0], "mixed 模式应按 modid 数量降序，热门优先")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
