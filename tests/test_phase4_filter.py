"""测试 Phase 4 过滤 — DB 查询与写入逻辑。"""
import json
import unittest

from src.models import verdict_int_to_str, verdict_str_to_int, _format_diagnoses


class TestIntVerdictToStr(unittest.TestCase):

    def test_all_values_display(self):
        self.assertEqual(verdict_int_to_str(0), "PASS")
        self.assertEqual(verdict_int_to_str(1), "⚠️ SUGGEST")
        self.assertEqual(verdict_int_to_str(2), "🔶 REVIEW")
        self.assertEqual(verdict_int_to_str(3), "❌ FAIL")

    def test_all_values_llm(self):
        self.assertEqual(verdict_int_to_str(0, llm=True), "PASS")
        self.assertEqual(verdict_int_to_str(1, llm=True), "SUGGEST")
        self.assertEqual(verdict_int_to_str(2, llm=True), "REVIEW")
        self.assertEqual(verdict_int_to_str(3, llm=True), "FAIL")

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            verdict_int_to_str(999)
        with self.assertRaises(ValueError):
            verdict_int_to_str(-1)
        with self.assertRaises(ValueError):
            verdict_int_to_str(999, llm=True)
        with self.assertRaises(ValueError):
            verdict_int_to_str(-1, llm=True)


class TestStrVerdictToInt(unittest.TestCase):

    def test_exact_match_display(self):
        self.assertEqual(verdict_str_to_int("PASS"), 0)
        self.assertEqual(verdict_str_to_int("⚠️ SUGGEST"), 1)
        self.assertEqual(verdict_str_to_int("🔶 REVIEW"), 2)
        self.assertEqual(verdict_str_to_int("❌ FAIL"), 3)

    def test_exact_match_llm(self):
        self.assertEqual(verdict_str_to_int("SUGGEST"), 1)
        self.assertEqual(verdict_str_to_int("REVIEW"), 2)
        self.assertEqual(verdict_str_to_int("FAIL"), 3)

    def test_strip_whitespace(self):
        self.assertEqual(verdict_str_to_int("  PASS  "), 0)
        self.assertEqual(verdict_str_to_int("\t❌ FAIL\n"), 3)

    def test_case_insensitive_keyword(self):
        self.assertEqual(verdict_str_to_int("fail"), 3)
        self.assertEqual(verdict_str_to_int("FAIL"), 3)
        self.assertEqual(verdict_str_to_int("review"), 2)
        self.assertEqual(verdict_str_to_int("REVIEW"), 2)
        self.assertEqual(verdict_str_to_int("suggest"), 1)
        self.assertEqual(verdict_str_to_int("SUGGEST"), 1)
        self.assertEqual(verdict_str_to_int("pass"), 0)
        self.assertEqual(verdict_str_to_int("PASS"), 0)

    def test_keyword_with_noise(self):
        self.assertEqual(verdict_str_to_int("verdict: FAIL"), 3)
        self.assertEqual(verdict_str_to_int("⚠ FAIL"), 3)

    def test_unrecognized_raises(self):
        with self.assertRaises(ValueError):
            verdict_str_to_int("UNKNOWN")
        with self.assertRaises(ValueError):
            verdict_str_to_int("")
        with self.assertRaises(ValueError):
            verdict_str_to_int("   ")


class TestFormatDiagnosesForFilter(unittest.TestCase):

    def test_empty_array(self):
        self.assertEqual(_format_diagnoses("[]"), "")

    def test_single_diagnosis(self):
        diags = json.dumps([{"source": "format_check", "reason": "格式错误"}])
        result = _format_diagnoses(diags)
        self.assertIn("格式错误", result)

    def test_multiple_diagnoses(self):
        diags = json.dumps([
            {"source": "format_check", "reason": "格式错误"},
            {"source": "terminology_check", "reason": "术语不一致"},
        ])
        result = _format_diagnoses(diags)
        self.assertIn("格式错误", result)
        self.assertIn("术语不一致", result)

    def test_empty_reason_skipped(self):
        diags = json.dumps([
            {"source": "format_check", "reason": ""},
            {"source": "terminology_check", "reason": "术语不一致"},
        ])
        result = _format_diagnoses(diags)
        self.assertIn("术语不一致", result)
        self.assertNotIn("格式错误", result)

    def test_invalid_json(self):
        self.assertEqual(_format_diagnoses("not json"), "")

    def test_non_list(self):
        self.assertEqual(_format_diagnoses('{"a":1}'), "")


if __name__ == "__main__":
    unittest.main()
