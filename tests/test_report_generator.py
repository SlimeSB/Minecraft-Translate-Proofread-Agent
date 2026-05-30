"""测试报告生成器 — verdict 收集、统计、报告构建。"""
import unittest
import tempfile
import shutil
from pathlib import Path

from src.models import AlignmentDict, EntryDict, VerdictDict
from src.reporting.report_generator import ReportGenerator


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

    def test_build_report_single_verdict_per_key(self):
        """新设计：Phase 5 传入已合并的单一列表，collect 不再做跨列表合并。"""
        v: list[VerdictDict] = [
            {"key": "item.sword", "verdict": "❌ FAIL", "reason": "reason-A; reason-B"},
        ]
        self.rg.collect(v)
        report = self.rg.build_report()
        vdict = report["verdicts"][0]
        self.assertIn("reason-A", vdict["reason"])
        self.assertIn("reason-B", vdict["reason"])

    def test_build_report_duplicate_key_keeps_highest_verdict(self):
        """同 key 多条时保留最高 verdict。"""
        v: list[VerdictDict] = [
            {"key": "item.sword", "verdict": "⚠️ SUGGEST", "reason": "reason-A"},
            {"key": "item.sword", "verdict": "❌ FAIL", "reason": "reason-B"},
        ]
        self.rg.collect(v)
        report = self.rg.build_report()
        self.assertEqual(len(report["verdicts"]), 1)
        vdict = report["verdicts"][0]
        self.assertEqual(vdict["verdict"], "❌ FAIL")

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

    def test_verdict_rank_sorting(self):
        """verdict 按严重性排序：FAIL > REVIEW > SUGGEST > PASS。"""
        v: list[VerdictDict] = [
            {"key": "a", "verdict": "PASS", "reason": ""},
            {"key": "b", "verdict": "❌ FAIL", "reason": ""},
            {"key": "c", "verdict": "⚠️ SUGGEST", "reason": ""},
            {"key": "d", "verdict": "🔶 REVIEW", "reason": ""},
        ]
        self.rg.collect(v)
        report = self.rg.build_report()
        verdicts = [m["verdict"] for m in report["verdicts"]]
        self.assertEqual(verdicts, ["❌ FAIL", "🔶 REVIEW", "⚠️ SUGGEST", "PASS"])


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
        import tempfile
        from src.pipeline.phase5_report import _generate_namespace_md
        from pathlib import Path
        tmpdir = tempfile.mkdtemp()
        try:
            verdicts: list[VerdictDict] = [
                {"key": "item.a", "verdict": "❌ FAIL", "reason": "test", "file_path": "path/to/file.json"},
            ]
            ns_dir = Path(tmpdir)
            _generate_namespace_md("test_ns", verdicts, {"total": 1, "issues": 1, "fail": 1, "suggest": 0, "review": 0}, ns_dir)
            md_path = ns_dir / "report.md"
            self.assertTrue(md_path.exists())
            content = md_path.read_text(encoding="utf-8")
            self.assertIn("| 判定 | 键名 | 文件路径 | 问题 |", content)
            self.assertIn("| ❌ FAIL |", content)
            self.assertIn("| `item.a` |", content)
            self.assertIn("| `path/to/file.json` |", content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestFormatDiagnoses(unittest.TestCase):
    """测试 _format_diagnoses 函数。"""
    import json as _json

    def test_empty_array(self):
        from src.models import _format_diagnoses
        self.assertEqual(_format_diagnoses("[]"), "")

    def test_single(self):
        from src.models import _format_diagnoses
        diags = self._json.dumps([{"source": "format_check", "reason": "格式错误"}])
        result = _format_diagnoses(diags)
        self.assertEqual(result, "[format_check] 格式错误")

    def test_multiple(self):
        from src.models import _format_diagnoses
        diags = self._json.dumps([
            {"source": "format_check", "reason": "格式错误"},
            {"source": "terminology_check", "reason": "术语不一致"},
        ])
        result = _format_diagnoses(diags)
        self.assertIn("[format_check] 格式错误", result)
        self.assertIn("[terminology_check] 术语不一致", result)

    def test_dedup(self):
        from src.models import _format_diagnoses
        diags = self._json.dumps([
            {"source": "format_check", "reason": "格式错误"},
            {"source": "format_check", "reason": "格式错误"},
        ])
        result = _format_diagnoses(diags)
        # 应该只出现一次
        self.assertEqual(result.count("[format_check] 格式错误"), 1)

    def test_empty_reason_skipped(self):
        from src.models import _format_diagnoses
        diags = self._json.dumps([
            {"source": "format_check", "reason": ""},
            {"source": "terminology_check", "reason": "术语不一致"},
        ])
        result = _format_diagnoses(diags)
        self.assertNotIn("format_check", result)

    def test_invalid_json(self):
        from src.models import _format_diagnoses
        self.assertEqual(_format_diagnoses("not json"), "")


if __name__ == "__main__":
    unittest.main()
