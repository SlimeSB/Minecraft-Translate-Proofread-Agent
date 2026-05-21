"""测试报告生成器 — verdict 合并去重与报告构建。"""
import unittest

from src.models import AlignmentDict, VerdictDict
from src.reporting.report_generator import (
    merge_verdicts, ReportGenerator, VERDICT_PRIORITY
)


class TestMergeVerdicts(unittest.TestCase):

    def test_empty_inputs(self):
        self.assertEqual(merge_verdicts(), [])
        self.assertEqual(merge_verdicts([], []), [])

    def test_single_list_passthrough(self):
        v: list[VerdictDict] = [{"key": "a.b", "verdict": "❌ FAIL", "reason": "bad"}]
        merged = merge_verdicts(v)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["key"], "a.b")

    def test_same_key_highest_priority_wins(self):
        fmt: list[VerdictDict] = [{"key": "x", "verdict": "⚠️ SUGGEST", "reason": "fmt", "source": "format_check"}]
        term: list[VerdictDict] = [{"key": "x", "verdict": "❌ FAIL", "reason": "term", "source": "terminology_check"}]
        merged = merge_verdicts(fmt, term)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["verdict"], "❌ FAIL")
        self.assertIn("fmt", merged[0]["reason"])
        self.assertIn("term", merged[0]["reason"])

    def test_different_keys_all_kept(self):
        a: list[VerdictDict] = [{"key": "a", "verdict": "❌ FAIL", "reason": "r1"}]
        b: list[VerdictDict] = [{"key": "b", "verdict": "⚠️ SUGGEST", "reason": "r2"}]
        merged = merge_verdicts(a, b)
        self.assertEqual(len(merged), 2)

    def test_same_key_same_priority_llm_wins(self):
        fmt: list[VerdictDict] = [{"key": "x", "verdict": "❌ FAIL", "reason": "fmt", "source": "format_check"}]
        llm: list[VerdictDict] = [{"key": "x", "verdict": "❌ FAIL", "reason": "llm", "source": "llm_review"}]
        merged = merge_verdicts(fmt, llm)
        self.assertEqual(merged[0]["source"], "llm_review")

    def test_keep_all_mode(self):
        v1: list[VerdictDict] = [{"key": "a", "verdict": "❌ FAIL", "reason": "r1"}]
        v2: list[VerdictDict] = [{"key": "a", "verdict": "⚠️ SUGGEST", "reason": "r2"}]
        merged = merge_verdicts(v1, v2, keep_all=True)
        self.assertEqual(len(merged), 2)

    def test_keep_all_dedups_identical(self):
        v: list[VerdictDict] = [{"key": "a", "verdict": "❌ FAIL", "reason": "same"}]
        merged = merge_verdicts(v, v, keep_all=True)
        self.assertEqual(len(merged), 1)

    def test_sorted_by_priority_desc(self):
        v: list[VerdictDict] = [
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
            ],
            "missing_zh": [], "extra_zh": [], "suspicious_untranslated": [],
            "stats": {"matched": 3, "missing_zh": 0, "extra_zh": 0, "suspicious_untranslated": 0, "total_en": 3, "total_zh": 3},
        })  # type: ignore[arg-type]

    def test_collect_and_stats(self):
        v: list[VerdictDict] = [
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
        v: list[VerdictDict] = [
            {"key": "item.sword", "verdict": "❌ FAIL", "reason": "wrong", "suggestion": "长剑", "source": "format_check"},
            {"key": "item.shield", "verdict": "PASS", "reason": "", "source": ""},
        ]
        self.rg.collect(v)
        report = self.rg.build_report()
        self.assertIn("stats", report)
        self.assertIn("verdicts", report)
        self.assertEqual(report["stats"]["total"], 3)

    def test_build_report_fills_en_zh_from_alignment(self):
        v: list[VerdictDict] = [
            {"key": "item.bow", "verdict": "❌ FAIL", "reason": "wrong"},
        ]
        self.rg.collect(v)
        report = self.rg.build_report()
        vdict = report["verdicts"][0]
        self.assertEqual(vdict["en_current"], "Bow")
        self.assertEqual(vdict["zh_current"], "弓")
        self.assertEqual(vdict.get("namespace"), "mod_b")

    def test_build_report_normalizes_verdict(self):
        v: list[VerdictDict] = [{"key": "item.sword", "verdict": "FAIL", "reason": "bad"}]
        self.rg.collect(v)
        report = self.rg.build_report()
        self.assertEqual(report["verdicts"][0]["verdict"], "❌ FAIL")

    def test_build_report_merges_reasons_for_same_key(self):
        v1: list[VerdictDict] = [{"key": "item.sword", "verdict": "❌ FAIL", "reason": "reason-A"}]
        v2: list[VerdictDict] = [{"key": "item.sword", "verdict": "⚠️ SUGGEST", "reason": "reason-B"}]
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
        v: list[VerdictDict] = [
            {"key": "item.sword", "verdict": "PASS", "reason": ""},
        ]
        self.rg.collect(v)
        stats = self.rg.compute_stats()
        self.assertEqual(stats["❌ FAIL"], 0)
        self.assertEqual(stats["⚠️ SUGGEST"], 0)
        self.assertEqual(stats["🔶 REVIEW"], 0)


class TestPhase5MultiVersion(unittest.TestCase):
    """测试 Phase 5 多版本三级目录输出结构。"""

    def test_build_slug_ver_ns_map_empty(self):
        from src.pipeline.phase5_report import _build_slug_ver_ns_map
        result = _build_slug_ver_ns_map([], [])
        self.assertEqual(result, {})

    def test_build_slug_ver_ns_map_single(self):
        from src.pipeline.phase5_report import _build_slug_ver_ns_map
        from src.models import EntryDict
        verdicts: list[VerdictDict] = [
            {"key": "item.a", "verdict": "❌ FAIL", "reason": "bad", "namespace": "mod_a", "version": "1.21"},
        ]
        entries: list[EntryDict] = [
            {"key": "item.a", "slug": "mod_a", "version": "1.21", "namespace": "mod_a"},  # type: ignore[typeddict-item]
        ]
        result = _build_slug_ver_ns_map(verdicts, entries)
        self.assertIn("mod_a", result)
        self.assertIn("1.21", result["mod_a"])
        self.assertIn("mod_a", result["mod_a"]["1.21"])
        info = result["mod_a"]["1.21"]["mod_a"]
        self.assertEqual(info["total"], 1)
        self.assertEqual(info["issues"], 1)
        self.assertEqual(info["fail"], 1)

    def test_build_slug_ver_ns_map_multi_version(self):
        from src.pipeline.phase5_report import _build_slug_ver_ns_map
        from src.models import EntryDict
        verdicts: list[VerdictDict] = [
            {"key": "a", "verdict": "❌ FAIL", "reason": "bad", "namespace": "mod_a", "version": "1.21"},
            {"key": "b", "verdict": "⚠️ SUGGEST", "reason": "meh", "namespace": "mod_a", "version": "1.20.1"},
            {"key": "c", "verdict": "PASS", "reason": "", "namespace": "mod_a", "version": "1.20.1"},
        ]
        entries: list[EntryDict] = [
            {"key": "a", "slug": "mod_a", "version": "1.21", "namespace": "mod_a"},  # type: ignore[typeddict-item]
            {"key": "b", "slug": "mod_a", "version": "1.20.1", "namespace": "mod_a"},  # type: ignore[typeddict-item]
            {"key": "c", "slug": "mod_a", "version": "1.20.1", "namespace": "mod_a"},  # type: ignore[typeddict-item]
        ]
        result = _build_slug_ver_ns_map(verdicts, entries)
        self.assertIn("1.21", result["mod_a"])
        self.assertIn("1.20.1", result["mod_a"])

        info_v121 = result["mod_a"]["1.21"]["mod_a"]
        self.assertEqual(info_v121["total"], 1)
        self.assertEqual(info_v121["fail"], 1)

        info_v1201 = result["mod_a"]["1.20.1"]["mod_a"]
        self.assertEqual(info_v1201["total"], 2)
        self.assertEqual(info_v1201["issues"], 1)
        self.assertEqual(info_v1201["suggest"], 1)

    def test_md_table_has_file_path_column(self):
        import tempfile, os
        from src.pipeline.phase5_report import _generate_namespace_md
        tmpdir = tempfile.mkdtemp()
        ns_dir = type("D", (), {"__truediv__": lambda s, x: type(s)(x)})()  # dummy
        try:
            # We just verify the function doesn't crash and produces expected headers
            verdicts: list[VerdictDict] = [
                {"key": "item.a", "verdict": "❌ FAIL", "reason": "test", "file_path": "path/to/file.json"},
            ]
            import pathlib
            ns_dir = pathlib.Path(tmpdir)
            _generate_namespace_md("test_ns", verdicts, {"total": 1, "issues": 1, "fail": 1, "suggest": 0, "review": 0}, ns_dir)
            md_path = ns_dir / "report.md"
            self.assertTrue(md_path.exists())
            content = md_path.read_text(encoding="utf-8")
            self.assertIn("| 判定 | 键名 | 文件路径 | 问题 |", content)
            self.assertIn("| ❌ FAIL |", content)
            self.assertIn("| `item.a` |", content)
            self.assertIn("| `path/to/file.json` |", content)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
