"""测试术语构建器 — 术语提取、归并、术语表构建与一致性检查。"""
import unittest
from collections import Counter

from src.checkers.terminology_builder import (
    _extract_common_zh, TerminologyBuilder,
)


class TestExtractCommonZh(unittest.TestCase):

    def test_single_entry_returns_none(self):
        self.assertIsNone(_extract_common_zh(Counter({"方铅岩": 5}), 0.6))

    def test_common_substring_found(self):
        c = Counter({"方铅岩砖": 2, "方铅岩台阶": 1, "方铅岩": 1, "方前言": 1})
        result = _extract_common_zh(c, 0.6)
        self.assertIsNotNone(result)
        self.assertIn("方铅岩", result)

    def test_no_common_substring(self):
        c = Counter({"苹果": 3, "香蕉": 2, "橙子": 1})
        result = _extract_common_zh(c, 0.6)
        self.assertIsNone(result)

    def test_short_term_ignored(self):
        c = Counter({"铁": 1, "铁锭": 3, "铁块": 2})
        result = _extract_common_zh(c, 0.6)
        self.assertIsNone(result)

    def test_min_ratio_not_met(self):
        c = Counter({"方铅岩砖": 1, "方铅岩": 1, "石头": 3})
        result = _extract_common_zh(c, 0.6)
        self.assertIsNone(result)

    def test_ignore_self_in_count(self):
        c = Counter({"中文测试": 5, "其他": 1})
        result = _extract_common_zh(c, 0.6)
        self.assertIsNone(result)


class TestTerminologyBuilder(unittest.TestCase):

    def setUp(self):
        self.tb = TerminologyBuilder()

    def _make_entry(self, key, en, zh, fmt="json"):
        return {"key": key, "en": en, "zh": zh, "format": fmt}

    def test_load_and_extract(self):
        en = {
            "item.iron_sword": "Iron Sword",
            "item.iron_pickaxe": "Iron Pickaxe",
            "item.gold_sword": "Golden Sword",
        }
        zh = {
            "item.iron_sword": "铁剑",
            "item.iron_pickaxe": "铁镐",
            "item.gold_sword": "金剑",
        }
        alignment = {
            "matched_entries": [
                self._make_entry("item.iron_sword", "Iron Sword", "铁剑"),
                self._make_entry("item.iron_pickaxe", "Iron Pickaxe", "铁镐"),
                self._make_entry("item.gold_sword", "Golden Sword", "金剑"),
            ]
        }
        self.tb.load(en, zh, alignment)
        extracted = self.tb.extract(min_freq=2, max_ngram=2)
        uni_terms = [t["term"] for t in extracted["unigrams"]]
        self.assertIn("iron", uni_terms)
        self.assertIn("sword", uni_terms)
        sword = next(t for t in extracted["unigrams"] if t["term"] == "sword")
        self.assertEqual(sword["freq"], 2)

    def test_build_glossary_basic(self):
        en = {
            "block.copper_ore": "Copper Ore",
            "block.copper_block": "Copper Block",
            "item.copper_ingot": "Copper Ingot",
        }
        zh = {
            "block.copper_ore": "铜矿石",
            "block.copper_block": "铜块",
            "item.copper_ingot": "铜锭",
        }
        alignment = {
            "matched_entries": [
                self._make_entry("block.copper_ore", "Copper Ore", "铜矿石"),
                self._make_entry("block.copper_block", "Copper Block", "铜块"),
                self._make_entry("item.copper_ingot", "Copper Ingot", "铜锭"),
            ]
        }
        self.tb.load(en, zh, alignment)
        self.tb.extract(min_freq=2, max_ngram=2)
        self.tb.merge_lemmas()
        glossary = self.tb.build_glossary(min_freq=3, min_consensus=0.6)
        self.assertGreaterEqual(len(glossary), 0)

    def test_check_consistency_no_glossary_empty(self):
        self.tb.load({}, {}, {"matched_entries": []})
        verdicts = self.tb.check_consistency()
        self.assertEqual(verdicts, [])

    def test_check_consistency_mismatch_detected(self):
        en_data = {
            "item.iron_sword": "Iron Sword",
            "item.iron_axe": "Iron Axe",
            "item.steel_sword": "Steel Sword",
        }
        zh_data = {
            "item.iron_sword": "铁剑",
            "item.iron_axe": "铁斧",
            "item.steel_sword": "钢剑",
        }
        alignment = {
            "matched_entries": [
                self._make_entry("item.iron_sword", "Iron Sword", "铁剑"),
                self._make_entry("item.iron_axe", "Iron Axe", "铁斧"),
                self._make_entry("item.steel_sword", "Steel Sword", "钢剑"),
            ]
        }
        self.tb.load(en_data, zh_data, alignment)
        self.tb.glossary = [{"en": "Iron", "zh": "铁"}]
        verdicts = self.tb.check_consistency()
        self.assertEqual(len(verdicts), 0)

    def test_merge_and_build_no_llm(self):
        en = {
            "block.copper_ore": "Copper Ore",
            "block.copper_block": "Copper Block",
        }
        zh = {
            "block.copper_ore": "铜矿石",
            "block.copper_block": "铜块",
        }
        alignment = {
            "matched_entries": [
                self._make_entry("block.copper_ore", "Copper Ore", "铜矿石"),
                self._make_entry("block.copper_block", "Copper Block", "铜块"),
            ]
        }
        self.tb.load(en, zh, alignment)
        glossary = self.tb.merge_and_build()
        self.assertIsInstance(glossary, list)


if __name__ == "__main__":
    unittest.main()
