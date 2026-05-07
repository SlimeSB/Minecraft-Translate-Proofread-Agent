"""测试键对齐模块。"""
import unittest

from src.tools.key_alignment import align_keys


class TestAlignKeys(unittest.TestCase):
    def test_basic_alignment(self):
        """基本对齐：全部匹配。"""
        en = {"item.sword": "Iron Sword", "item.shield": "Iron Shield"}
        zh = {"item.sword": "铁剑", "item.shield": "铁盾牌"}
        result = align_keys(en, zh)
        self.assertEqual(result["stats"]["matched"], 2)
        self.assertEqual(result["stats"]["missing_zh"], 0)
        self.assertEqual(result["stats"]["extra_zh"], 0)
        self.assertEqual(len(result["matched_entries"]), 2)
        self.assertTrue(
            any(e["key"] == "item.sword" and e["en"] == "Iron Sword" and e["zh"] == "铁剑"
                for e in result["matched_entries"])
        )

    def test_missing_zh(self):
        """检测缺失的翻译。"""
        en = {"item.sword": "Iron Sword", "item.shield": "Iron Shield"}
        zh = {"item.sword": "铁剑"}
        result = align_keys(en, zh)
        self.assertEqual(result["stats"]["missing_zh"], 1)
        self.assertEqual(len(result["missing_zh"]), 1)
        self.assertEqual(result["missing_zh"][0]["key"], "item.shield")

    def test_extra_zh(self):
        """检测多余的键。"""
        en = {"item.sword": "Iron Sword"}
        zh = {"item.sword": "铁剑", "item.bow": "弓"}
        result = align_keys(en, zh)
        self.assertEqual(result["stats"]["extra_zh"], 1)
        self.assertEqual(len(result["extra_zh"]), 1)
        self.assertEqual(result["extra_zh"][0]["key"], "item.bow")

    def test_suspicious_untranslated(self):
        """zh==en 且非代码应标记为疑似未翻译。"""
        en = {"item.sword": "Iron Sword"}
        zh = {"item.sword": "Iron Sword"}
        result = align_keys(en, zh)
        self.assertEqual(result["stats"]["suspicious_untranslated"], 1)
        self.assertEqual(result["suspicious_untranslated"][0]["key"], "item.sword")

    def test_code_not_suspicious(self):
        """全大写常量 zh==en 不应标记为疑似未翻译。"""
        en = {"gui.title": "MENU"}
        zh = {"gui.title": "MENU"}
        result = align_keys(en, zh)
        self.assertEqual(result["stats"]["suspicious_untranslated"], 0)

    def test_mixed_scenario(self):
        """综合场景。"""
        en = {"a": "Apple", "b": "Banana", "c": "Cherry", "d": "DURIAN"}
        zh = {"a": "苹果", "c": "Cherry", "d": "DURIAN", "e": "Elderberry"}
        result = align_keys(en, zh)
        self.assertEqual(result["stats"]["matched"], 3)       # a, c, d
        self.assertEqual(result["stats"]["missing_zh"], 1)     # b
        self.assertEqual(result["stats"]["extra_zh"], 1)       # e
        # c="Cherry" is alpha-only (matches code-like regex), d="DURIAN" is ALL_CAPS
        self.assertEqual(result["stats"]["suspicious_untranslated"], 0)

    def test_empty_inputs(self):
        """空输入。"""
        result = align_keys({}, {})
        self.assertEqual(result["stats"]["matched"], 0)
        self.assertEqual(result["stats"]["missing_zh"], 0)
        self.assertEqual(result["stats"]["extra_zh"], 0)


if __name__ == "__main__":
    unittest.main()
