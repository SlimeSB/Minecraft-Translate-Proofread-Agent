"""测试报告生成器 — verdict 合并去重与报告构建。"""
import unittest

from src.reporting.report_generator import (
    merge_verdicts, ReportGenerator, VERDICT_PRIORITY
)


class TestMergeVerdicts(unittest.TestCase):

    def test_empty_inputs(self):
        self.assertEqual(merge_verdicts(), [])
        self.assertEqual(merge_verdicts([], []), [])

    def test_single_list_passthrough(self):
        v = [{"key": "a.b", "verdict": "❌ FAIL", "reason": "bad"}]
        merged = merge_verdicts(v)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["key"], "a.b")

    def test_same_key_highest_priority_wins(self):
        fmt = [{"key": "x", "verdict": "⚠️ SUGGEST", "reason": "fmt", "source": "format_check"}]
        term = [{"key": "x", "verdict": "❌ FAIL", "reason": "term", "source": "terminology_check"}]
        merged = merge_verdicts(fmt, term)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["verdict"], "❌ FAIL")
        self.assertIn("fmt", merged[0]["reason"])
        self.assertIn("term", merged[0]["reason"])

    def test_different_keys_all_kept(self):
        a = [{"key": "a", "verdict": "❌ FAIL", "reason": "r1"}]
        b = [{"key": "b", "verdict": "⚠️ SUGGEST", "reason": "r2"}]
        merged = merge_verdicts(a, b)
        self.assertEqual(len(merged), 2)

    def test_same_key_same_priority_llm_wins(self):
        fmt = [{"key": "x", "verdict": "❌ FAIL", "reason": "fmt", "source": "format_check"}]
        llm = [{"key": "x", "verdict": "❌ FAIL", "reason": "llm", "source": "llm_review"}]
        merged = merge_verdicts(fmt, llm)
        self.assertEqual(merged[0]["source"], "llm_review")

    def test_keep_all_mode(self):
        v1 = [{"key": "a", "verdict": "❌ FAIL", "reason": "r1"}]
        v2 = [{"key": "a", "verdict": "⚠️ SUGGEST", "reason": "r2"}]
        merged = merge_verdicts(v1, v2, keep_all=True)
        self.assertEqual(len(merged), 2)

    def test_keep_all_dedups_identical(self):
        v = [{"key": "a", "verdict": "❌ FAIL", "reason": "same"}]
        merged = merge_verdicts(v, v, keep_all=True)
        self.assertEqual(len(merged), 1)

    def test_sorted_by_priority_desc(self):
        v = [
            {"key": "a", "verdict": "PASS", "reason": ""},
            {"key": "b", "verdict": "❌ FAIL", "reason": ""},
            {"key": "c", "verdict": "⚠️ SUGGEST", "reason": ""},
            {"key": "d", "verdict": "🔶 REVIEW", "reason": ""},
        ]
        merged = merge_verdicts(v)
        verdicts = [m["verdict"] for m in merged]
        self.assertEqual(verdicts, ["❌ FAIL", "🔶 REVIEW", "⚠️ SUGGEST", "PASS"])


class TestReportGenerator(unittest.TestCase):

    def setUp(self):
        self.rg = ReportGenerator()
        self.rg.load_alignment({
            "matched_entries": [
                {"key": "item.sword", "en": "Sword", "zh": "剑", "namespace": "mod_a"},
                {"key": "item.shield", "en": "Shield", "zh": "盾", "namespace": "mod_a"},
                {"key": "item.bow", "en": "Bow", "zh": "弓", "namespace": "mod_b"},
            ]
        })

    def test_collect_and_stats(self):
        v = [
            {"key": "item.sword", "verdict": "❌ FAIL", "reason": "bad"},
            {"key": "item.shield", "verdict": "⚠️ SUGGEST", "reason": "meh"},
            {"key": "item.bow", "verdict": "PASS", "reason": ""},
        ]
        self.rg.collect(v)
        stats = self.rg.compute_stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["PASS"], 1)
        self.assertEqual(stats["❌ FAIL"], 1)
        self.assertEqual(stats["⚠️ SUGGEST"], 1)
        self.assertEqual(stats["🔶 REVIEW"], 0)

    def test_build_report_structure(self):
        v = [
            {"key": "item.sword", "verdict": "❌ FAIL", "reason": "wrong", "suggestion": "长剑", "source": "format_check"},
            {"key": "item.shield", "verdict": "PASS", "reason": "", "source": ""},
        ]
        self.rg.collect(v)
        report = self.rg.build_report()
        self.assertIn("stats", report)
        self.assertIn("verdicts", report)
        self.assertEqual(report["stats"]["total"], 3)

    def test_build_report_fills_en_zh_from_alignment(self):
        v = [
            {"key": "item.bow", "verdict": "❌ FAIL", "reason": "wrong"},
        ]
        self.rg.collect(v)
        report = self.rg.build_report()
        vdict = report["verdicts"][0]
        self.assertEqual(vdict["en_current"], "Bow")
        self.assertEqual(vdict["zh_current"], "弓")
        self.assertEqual(vdict["namespace"], "mod_b")

    def test_build_report_normalizes_verdict(self):
        v = [{"key": "item.sword", "verdict": "FAIL", "reason": "bad"}]
        self.rg.collect(v)
        report = self.rg.build_report()
        self.assertEqual(report["verdicts"][0]["verdict"], "❌ FAIL")

    def test_build_report_merges_reasons_for_same_key(self):
        v1 = [{"key": "item.sword", "verdict": "❌ FAIL", "reason": "reason-A"}]
        v2 = [{"key": "item.sword", "verdict": "⚠️ SUGGEST", "reason": "reason-B"}]
        self.rg.collect(v1, v2)
        report = self.rg.build_report()
        vdict = report["verdicts"][0]
        self.assertIn("reason-A", vdict["reason"])
        self.assertIn("reason-B", vdict["reason"])

    def test_empty_collect_no_crash(self):
        self.rg.collect()
        stats = self.rg.compute_stats()
        self.assertEqual(stats["PASS"], 3)
        report = self.rg.build_report()
        self.assertEqual(len(report["verdicts"]), 0)

    def test_compute_stats_all_pass(self):
        v = [
            {"key": "item.sword", "verdict": "PASS", "reason": ""},
        ]
        self.rg.collect(v)
        stats = self.rg.compute_stats()
        self.assertEqual(stats["❌ FAIL"], 0)
        self.assertEqual(stats["⚠️ SUGGEST"], 0)
        self.assertEqual(stats["🔶 REVIEW"], 0)


if __name__ == "__main__":
    unittest.main()
