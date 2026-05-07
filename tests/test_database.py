"""测试 PipelineDB — SQLite 数据库 CRUD 操作。"""
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

    def test_save_and_load_alignment(self):
        alignment = {
            "matched_entries": [
                {"key": "item.sword", "en": "Sword", "zh": "剑",
                 "format": "json", "namespace": "mod_a",
                 "_change": {"old_en": "Blade", "old_zh": "刀"}},
                {"key": "item.shield", "en": "Shield", "zh": "盾",
                 "format": "json", "namespace": "mod_a"},
            ]
        }
        self.db.save_alignment(alignment)
        loaded = self.db.load_alignment()
        self.assertEqual(loaded["stats"]["matched"], 2)
        entries = loaded["matched_entries"]
        self.assertEqual(entries[0]["key"], "item.sword")
        self.assertEqual(entries[0]["en"], "Sword")

    def test_save_and_load_glossary(self):
        glossary = [
            {"en": "copper", "zh": "铜"},
            {"en": "iron", "zh": "铁"},
        ]
        self.db.save_glossary(glossary)
        loaded = self.db.load_glossary()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["en"], "copper")
        self.assertEqual(loaded[0]["zh"], "铜")

    def test_save_and_load_verdicts(self):
        verdicts = [
            {"key": "item.sword", "en_current": "Sword", "zh_current": "剑",
             "verdict": "❌ FAIL", "suggestion": "长剑", "reason": "wrong",
             "source": "format_check", "namespace": "mod_a"},
            {"key": "item.shield", "en_current": "Shield", "zh_current": "盾",
             "verdict": "PASS", "suggestion": "", "reason": "",
             "source": "", "namespace": "mod_a"},
        ]
        self.db.save_verdicts(verdicts, "format")
        loaded = self.db.load_verdicts(phase="format")
        self.assertEqual(len(loaded), 2)

    def test_load_verdicts_by_namespace(self):
        verdicts = [
            {"key": "a", "namespace": "ns1"},
            {"key": "b", "namespace": "ns2"},
        ]
        self.db.save_verdicts(verdicts, "format")
        ns1 = self.db.load_verdicts(phase="format", namespace="ns1")
        self.assertEqual(len(ns1), 1)
        self.assertEqual(ns1[0]["key"], "a")

    def test_set_filtered_changes_verdict(self):
        verdicts = [{"key": "item.x", "verdict": "❌ FAIL", "reason": "bad"}]
        self.db.save_verdicts(verdicts, "merged")
        self.db.set_filtered("item.x", "PASS", "")
        loaded = self.db.load_verdicts(phase="merged", filtered=None)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["verdict"], "PASS")
        self.assertEqual(loaded[0]["_filtered"], 1)

    def test_set_filtered_only_affects_merged_phase(self):
        verdicts_fmt = [{"key": "item.x", "verdict": "❌ FAIL", "reason": "bad"}]
        verdicts_merged = [{"key": "item.x", "verdict": "❌ FAIL", "reason": "bad"}]
        self.db.save_verdicts(verdicts_fmt, "format")
        self.db.save_verdicts(verdicts_merged, "merged")
        self.db.set_filtered("item.x", "PASS", "")
        fmt_loaded = self.db.load_verdicts(phase="format", filtered=None)
        self.assertEqual(fmt_loaded[0]["verdict"], "❌ FAIL")

    def test_set_merged_reason(self):
        verdicts = [{"key": "item.x", "verdict": "❌ FAIL", "reason": "old"}]
        self.db.save_verdicts(verdicts, "merged")
        self.db.set_merged_reason("item.x", "new reason")
        loaded = self.db.load_verdicts(phase="merged", filtered=None)
        self.assertEqual(loaded[0]["reason"], "new reason")

    def test_get_merged_stats(self):
        verdicts = [
            {"key": "a", "verdict": "❌ FAIL", "reason": "bad"},
            {"key": "b", "verdict": "PASS", "reason": ""},
            {"key": "c", "verdict": "⚠️ SUGGEST", "reason": "meh"},
            {"key": "d", "verdict": "🔶 REVIEW", "reason": "check"},
        ]
        self.db.save_verdicts(verdicts, "merged")
        for v in verdicts:
            self.db.set_filtered(v["key"], v["verdict"], v.get("reason", ""))
        stats = self.db.get_merged_stats()
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["PASS"], 1)
        self.assertEqual(stats["❌ FAIL"], 1)
        self.assertEqual(stats["⚠️ SUGGEST"], 1)
        self.assertEqual(stats["🔶 REVIEW"], 1)

    def test_filter_cache(self):
        self.assertIsNone(self.db.lookup_filter_cache("abc123"))
        self.db.store_filter_cache("abc123", "PASS", "")
        self.db.commit_filter_cache()
        result = self.db.lookup_filter_cache("abc123")
        self.assertEqual(result, ("PASS", ""))
        self.assertEqual(self.db.filter_cache_size(), 1)

    def test_filter_cache_overwrite(self):
        self.db.store_filter_cache("key1", "KEEP", "old reason")
        self.db.commit_filter_cache()
        self.db.store_filter_cache("key1", "PASS", "")
        self.db.commit_filter_cache()
        result = self.db.lookup_filter_cache("key1")
        self.assertEqual(result, ("PASS", ""))
        self.assertEqual(self.db.filter_cache_size(), 1)

    def test_save_fuzzy_results(self):
        fm = {
            "item.a": [{"similarity": 85.0, "key": "item.b", "en": "Sword", "zh": "剑"}],
        }
        self.db.save_fuzzy_results(fm)
        loaded = self.db.load_fuzzy_results()
        self.assertIn("item.a", loaded)
        self.assertEqual(loaded["item.a"][0]["similarity"], 85.0)

    def test_meta_set_and_get(self):
        self.assertIsNone(self.db.get_meta("version"))
        self.db.set_meta("version", "1.0")
        self.assertEqual(self.db.get_meta("version"), "1.0")

    def test_meta_overwrite(self):
        self.db.set_meta("key", "old")
        self.db.set_meta("key", "new")
        self.assertEqual(self.db.get_meta("key"), "new")

    def test_save_alignment_overwrites(self):
        a1 = {"matched_entries": [{"key": "a", "en": "A", "zh": "甲"}]}
        a2 = {"matched_entries": [{"key": "b", "en": "B", "zh": "乙"}]}
        self.db.save_alignment(a1)
        self.db.save_alignment(a2)
        loaded = self.db.load_alignment()
        self.assertEqual(loaded["stats"]["matched"], 1)
        self.assertEqual(loaded["matched_entries"][0]["key"], "b")

    def test_save_verdicts_overwrites_by_phase(self):
        v1 = [{"key": "a", "verdict": "PASS"}]
        v2 = [{"key": "b", "verdict": "❌ FAIL"}]
        self.db.save_verdicts(v1, "format")
        self.db.save_verdicts(v2, "format")
        loaded = self.db.load_verdicts(phase="format")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["key"], "b")

    def test_save_glossary_overwrites(self):
        self.db.save_glossary([{"en": "a", "zh": "甲"}])
        self.db.save_glossary([{"en": "b", "zh": "乙"}])
        loaded = self.db.load_glossary()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["en"], "b")


if __name__ == "__main__":
    unittest.main()
