"""测试 Phase 4 过滤 — DB 查询与写入逻辑。"""
import json
import unittest

from src.models import verdict_int_to_str, _format_diagnoses


class TestIntVerdictToStr(unittest.TestCase):

    def test_all_values(self):
        self.assertEqual(verdict_int_to_str(0), "PASS")
        self.assertEqual(verdict_int_to_str(1), "⚠️ SUGGEST")
        self.assertEqual(verdict_int_to_str(2), "🔶 REVIEW")
        self.assertEqual(verdict_int_to_str(3), "❌ FAIL")

    def test_out_of_range(self):
        self.assertEqual(verdict_int_to_str(999), "PASS")


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
