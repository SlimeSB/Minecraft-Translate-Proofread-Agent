"""测试 PipelineDB — 新 entries 单表 schema。"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.storage.database import PipelineDB


class TestPipelineDB(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "pipeline.db"
        self.db = PipelineDB(self.db_path)

    def tearDown(self):
        self.db.close()
        for f in os.listdir(self.tmpdir):
            os.unlink(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def test_db_creates_file(self):
        self.assertTrue(self.db_path.exists())

    def test_entries_schema_creates_table(self):
        """新 schema：entries 表创建成功。"""
        self.db.execute(
            "INSERT INTO entries (key, en, zh) VALUES (?,?,?)",
            ("item.sword", "Sword", "剑"))
        self.db.commit()
        row = self.db.execute("SELECT * FROM entries WHERE key=?", ("item.sword",)).fetchone()
        self.assertEqual(row["key"], "item.sword")
        self.assertEqual(row["en"], "Sword")
        self.assertEqual(row["zh"], "剑")

    def test_entries_default_values(self):
        """新 schema：默认值正确。"""
        self.db.execute(
            "INSERT INTO entries (key, en, zh) VALUES (?,?,?)",
            ("item.shield", "Shield", "盾"))
        self.db.commit()
        row = self.db.execute("SELECT * FROM entries WHERE key=?", ("item.shield",)).fetchone()
        self.assertEqual(row["state"], 0)
        self.assertEqual(row["verdict"], 0)
        self.assertEqual(row["suggestion"], "")
        self.assertEqual(row["diagnoses"], "[]")
        self.assertEqual(row["format"], "")
        self.assertEqual(row["namespace"], "")
        self.assertEqual(row["version"], "")
        self.assertEqual(row["file_path"], "")
        self.assertEqual(row["slug"], "")
        self.assertEqual(row["old_en"], "")
        self.assertEqual(row["old_zh"], "")

    def test_insert_or_replace(self):
        """INSERT OR REPLACE：同一 key 后写入覆盖。"""
        self.db.execute(
            "INSERT OR REPLACE INTO entries (key, en, zh, state) VALUES (?,?,?,?)",
            ("item.x", "X", "某物", 0))
        self.db.execute(
            "INSERT OR REPLACE INTO entries (key, en, zh, state) VALUES (?,?,?,?)",
            ("item.x", "X_v2", "某物_v2", 1))
        self.db.commit()
        row = self.db.execute("SELECT * FROM entries WHERE key=?", ("item.x",)).fetchone()
        self.assertEqual(row["en"], "X_v2")
        self.assertEqual(row["state"], 1)

    def test_state_max_update(self):
        """state 使用 MAX(state, N) 单调推进。"""
        self.db.execute(
            "INSERT INTO entries (key, en, zh, state) VALUES (?,?,?,0)",
            ("item.a", "A", "甲"))
        self.db.commit()
        # 推进到 1
        self.db.execute("UPDATE entries SET state=MAX(state,1) WHERE key=?", ("item.a",))
        self.db.commit()
        row = self.db.execute("SELECT * FROM entries WHERE key=?", ("item.a",)).fetchone()
        self.assertEqual(row["state"], 1)
        # 推进到 2
        self.db.execute("UPDATE entries SET state=MAX(state,2) WHERE key=?", ("item.a",))
        self.db.commit()
        row = self.db.execute("SELECT * FROM entries WHERE key=?", ("item.a",)).fetchone()
        self.assertEqual(row["state"], 2)

    def test_verdict_max_update(self):
        """verdict 使用 MAX(verdict, N) 单调推进。"""
        self.db.execute(
            "INSERT INTO entries (key, en, zh, verdict) VALUES (?,?,?,0)",
            ("item.b", "B", "乙"))
        self.db.commit()
        # check: FAIL=3
        self.db.execute("UPDATE entries SET verdict=MAX(verdict,3) WHERE key=?", ("item.b",))
        self.db.commit()
        row = self.db.execute("SELECT * FROM entries WHERE key=?", ("item.b",)).fetchone()
        self.assertEqual(row["verdict"], 3)
        # PASS=0 < 3, should stay 3
        self.db.execute("UPDATE entries SET verdict=MAX(verdict,0) WHERE key=?", ("item.b",))
        self.db.commit()
        row = self.db.execute("SELECT * FROM entries WHERE key=?", ("item.b",)).fetchone()
        self.assertEqual(row["verdict"], 3)

    def test_diagnoses_json_append(self):
        """diagnoses JSON 数组追加/替换操作。"""
        self.db.execute(
            "INSERT INTO entries (key, en, zh, diagnoses) VALUES (?,?,?,'[]')",
            ("item.c", "C", "丙"))
        self.db.commit()
        # 追加 format_check 诊断
        diag1 = [{"source": "format_check", "reason": "格式错误"}]
        self.db.execute(
            "UPDATE entries SET diagnoses=? WHERE key=?",
            (json.dumps(diag1, ensure_ascii=False), "item.c"))
        self.db.commit()
        row = self.db.execute("SELECT diagnoses FROM entries WHERE key=?", ("item.c",)).fetchone()
        loaded = json.loads(row["diagnoses"])
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["source"], "format_check")

        # 追加 terminology_check 诊断
        loaded.append({"source": "terminology_check", "reason": "术语不一致"})
        self.db.execute(
            "UPDATE entries SET diagnoses=? WHERE key=?",
            (json.dumps(loaded, ensure_ascii=False), "item.c"))
        self.db.commit()
        row = self.db.execute("SELECT diagnoses FROM entries WHERE key=?", ("item.c",)).fetchone()
        loaded2 = json.loads(row["diagnoses"])
        self.assertEqual(len(loaded2), 2)

    def test_blanket_update(self):
        """blanket UPDATE 推进全部条目的 state。"""
        for i in range(3):
            self.db.execute(
                "INSERT INTO entries (key, en, zh, state) VALUES (?,?,?,0)",
                (f"item.{i}", f"EN{i}", f"ZH{i}"))
        self.db.commit()
        # 全部推进到 1
        self.db.execute("UPDATE entries SET state=MAX(state,1)")
        self.db.commit()
        rows = self.db.execute("SELECT state FROM entries").fetchall()
        for r in rows:
            self.assertEqual(r["state"], 1)

    def test_select_by_verdict(self):
        """按 verdict >= N 查询正常。"""
        data = [
            ("item.a", "A", "甲", 0),
            ("item.b", "B", "乙", 1),
            ("item.c", "C", "丙", 2),
            ("item.d", "D", "丁", 3),
        ]
        for key, en, zh, v in data:
            self.db.execute(
                "INSERT INTO entries (key, en, zh, verdict) VALUES (?,?,?,?)",
                (key, en, zh, v))
        self.db.commit()
        rows = self.db.execute("SELECT * FROM entries WHERE verdict >= 1").fetchall()
        self.assertEqual(len(rows), 3)  # verdict 1,2,3
        rows2 = self.db.execute("SELECT * FROM entries WHERE verdict >= 3").fetchall()
        self.assertEqual(len(rows2), 1)  # only FAIL

    def test_count_by_state(self):
        """SELECT COUNT 即时统计正确。"""
        self.db.execute(
            "INSERT INTO entries (key, en, zh, state) VALUES (?,?,?,0)",
            ("item.a", "A", "甲"))
        self.db.execute(
            "INSERT INTO entries (key, en, zh, state) VALUES (?,?,?,1)",
            ("item.b", "B", "乙"))
        self.db.execute(
            "INSERT INTO entries (key, en, zh, state) VALUES (?,?,?,2)",
            ("item.c", "C", "丙"))
        self.db.commit()
        count = self.db.execute("SELECT COUNT(*) FROM entries WHERE state >= 1").fetchone()[0]
        self.assertEqual(count, 2)

    def test_commit_and_close(self):
        self.db.execute(
            "INSERT INTO entries (key, en, zh) VALUES (?,?,?)",
            ("test.close", "Close", "关闭"))
        self.db.commit()
        self.db.close()
        # Reconnect
        db2 = PipelineDB(self.db_path)
        row = db2.execute("SELECT * FROM entries WHERE key=?", ("test.close",)).fetchone()
        self.assertEqual(row["key"], "test.close")
        db2.close()

    def test_old_verdicts_table_does_not_exist(self):
        """旧 verdicts 表不应创建。"""
        try:
            self.db.execute("SELECT * FROM verdicts")
            self.fail("旧 verdicts 表不应存在")
        except Exception:
            pass

    def test_old_alignment_table_does_not_exist(self):
        """旧 alignment 表不应创建。"""
        try:
            self.db.execute("SELECT * FROM alignment")
            self.fail("旧 alignment 表不应存在")
        except Exception:
            pass

    def test_old_glossary_table_does_not_exist(self):
        """旧 glossary 表不应创建。"""
        try:
            self.db.execute("SELECT * FROM glossary")
            self.fail("旧 glossary 表不应存在")
        except Exception:
            pass

    def test_old_filter_cache_table_does_not_exist(self):
        """旧 filter_cache 表不应创建。"""
        try:
            self.db.execute("SELECT * FROM filter_cache")
            self.fail("旧 filter_cache 表不应存在")
        except Exception:
            pass

    def test_context_manager(self):
        """__enter__ / __exit__ 正常工作。"""
        db_path = Path(self.tmpdir) / "ctx.db"
        with PipelineDB(db_path) as db:
            db.execute(
                "INSERT INTO entries (key, en, zh) VALUES (?,?,?)",
                ("ctx.test", "CTX", "上下文"))
            db.commit()
        # 确认连接已关闭，数据已持久化
        db2 = PipelineDB(db_path)
        row = db2.execute("SELECT * FROM entries WHERE key=?", ("ctx.test",)).fetchone()
        self.assertIsNotNone(row)
        db2.close()

    def test_pr_fields_preserved(self):
        """PR 模式字段 (old_en, old_zh, slug, version, file_path) 存储正确。"""
        self.db.execute(
            "INSERT INTO entries (key, en, zh, old_en, old_zh, slug, version, file_path) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("pr.key", "New EN", "新中文", "Old EN", "旧中文",
             "my_mod", "1.21", "path/to/file.json"))
        self.db.commit()
        row = self.db.execute("SELECT * FROM entries WHERE key=?", ("pr.key",)).fetchone()
        self.assertEqual(row["old_en"], "Old EN")
        self.assertEqual(row["old_zh"], "旧中文")
        self.assertEqual(row["slug"], "my_mod")
        self.assertEqual(row["version"], "1.21")
        self.assertEqual(row["file_path"], "path/to/file.json")


if __name__ == "__main__":
    unittest.main()
