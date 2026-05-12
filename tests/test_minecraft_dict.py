"""测试 MinecraftDictStore — load/lookup 两种模式/changes=0 择优/changes=1 全量/排序/版本匹配/边界情况。"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.dictionary.minecraft_dict import MinecraftDictStore


def _create_test_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE vanilla_keys (
            key TEXT NOT NULL,
            en_us TEXT,
            zh_cn TEXT,
            version_start TEXT NOT NULL,
            version_end TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'lang',
            changes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (key, version_start, category)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_vanilla_keys_key ON vanilla_keys(key)")
    conn.close()


def _insert(conn: sqlite3.Connection, key: str, en: str, zh: str,
            v_start: str, v_end: str, changes: int = 0) -> None:
    conn.execute(
        "INSERT INTO vanilla_keys (key, en_us, zh_cn, version_start, version_end, category, changes) "
        "VALUES (?, ?, ?, ?, ?, 'lang', ?)",
        (key, en, zh, v_start, v_end, changes),
    )


class TestMinecraftDictStore(unittest.TestCase):

    def _make_store_and_conn(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        _create_test_db(path)
        conn = sqlite3.connect(path)
        return path, conn, MinecraftDictStore(db_path=path)

    # 2.8: DB 不存在时静默
    def test_db_not_exists(self):
        store = MinecraftDictStore(db_path="/nonexistent/path_xyz.db")
        store.load()
        result = store.lookup("stone")
        self.assertEqual(result, "")

    # 2.4: 空结果
    def test_empty_result(self):
        path, conn, store = self._make_store_and_conn()
        try:
            conn.close()
            store.load()
            result = store.lookup("zzzznotexist")
            self.assertEqual(result, "")
        finally:
            store.close()
            Path(path).unlink(missing_ok=True)

    # 2.4: 空查询词
    def test_empty_query(self):
        path, conn, store = self._make_store_and_conn()
        try:
            store.load()
            result = store.lookup("")
            self.assertEqual(result, "")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=0 单条
    def test_changes0_single(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.stone", "Stone", "石头", "1.20.4", "1.21.1", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("stone")
            self.assertIn("石头", result)
            self.assertIn("1.20.4-1.21.1", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=0 多条
    def test_changes0_multiple(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.a", "Apple", "苹果", "1.20.0", "1.21.0")
            _insert(conn, "key.b", "Banana", "香蕉", "1.20.0", "1.21.0")
            _insert(conn, "key.c", "Cherry", "樱桃", "1.20.0", "1.21.0")
            conn.commit()
            store.load()
            result = store.lookup("apple")
            self.assertIn("苹果", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=0 通过单一术语匹配
    def test_changes0_single_term(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test stone block", "测试石头", "1.20.0", "1.21.0")
            conn.commit()
            store.load()
            result = store.lookup("stone")
            self.assertIn("测试石头", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=1 二次查询全量
    def test_changes1_full_history(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.open_realm", "Open realm", "打开Realm", "1.16.5", "1.18.2", changes=1)
            _insert(conn, "key.open_realm", "Open realm", "已打开Realm", "1.19.4", "1.20.1", changes=1)
            _insert(conn, "key.open_realm", "Open realm", "Reopen Realm", "26.1.2", "26.1.2", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("open realm")
            self.assertIn("打开Realm", result)
            self.assertIn("已打开Realm", result)
            self.assertIn("Reopen Realm", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=1 版本敏感 header
    def test_changes1_header(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "测试A", "1.16.0", "1.18.0", changes=1)
            _insert(conn, "key.test", "Test", "测试B", "1.19.0", "1.21.0", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("test")
            self.assertIn("版本敏感译名", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=0 也有 header
    def test_changes0_header(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.stone", "Stone", "石头", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("stone")
            self.assertIn("原版词典", result)
            self.assertNotIn("版本敏感译名", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # primary/sub 排序：target_version 匹配行优先
    def test_primary_sub_target_version(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "旧版", "1.16.5", "1.18.2", changes=1)
            _insert(conn, "key.test", "Test", "新版", "1.19.4", "1.21.1", changes=1)
            _insert(conn, "key.test", "Test", "最新", "26.1.2", "26.1.2", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("test", target_version="1.20.1")
            lines = [l for l in result.split("\n") if l.strip()]
            self.assertGreater(len(lines), 1)
            primary_line = lines[1]
            self.assertIn("新版", primary_line)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # primary/sub 排序：无 target 时最新优先
    def test_primary_sub_no_target(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "旧版", "1.16.5", "1.18.2", changes=1)
            _insert(conn, "key.test", "Test", "中版", "1.19.0", "1.20.0", changes=1)
            _insert(conn, "key.test", "Test", "最新", "26.1.2", "26.1.2", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("test")
            lines = [l for l in result.split("\n") if l.strip()]
            self.assertGreater(len(lines), 1)
            primary_line = lines[1]
            self.assertIn("最新", primary_line)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # sub 行前缀 "- "
    def test_sub_prefix(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "第一版", "1.16.0", "1.18.0", changes=1)
            _insert(conn, "key.test", "Test", "第二版", "1.19.0", "1.21.0", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("test")
            sub_lines = [l for l in result.split("\n") if l.startswith("- ")]
            self.assertEqual(len(sub_lines), 1)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 停用词过滤
    def test_stop_words_filtered(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.the", "The", "定冠词", "1.20.0", "1.21.0")
            conn.commit()
            store.load()
            result = store.lookup("the")
            self.assertEqual(result, "")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # close 方法
    def test_close(self):
        path, conn, store = self._make_store_and_conn()
        store.load()
        store.close()
        self.assertIsNone(store._conn)
        conn.close()
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
