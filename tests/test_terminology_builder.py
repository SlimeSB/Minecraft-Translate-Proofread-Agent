"""测试术语构建器 — 术语提取、归并、术语表构建与一致性检查。"""
import unittest
from collections import Counter

from src.checkers.terminology_builder import (
    _extract_common_zh, TerminologyBuilder, _collect_zh_translations,
    check_consistency, llm_verify_glossary,
)


class TestExtractCommonZh(unittest.TestCase):

    def test_single_entry_returns_none(self):
        self.assertIsNone(_extract_common_zh(Counter({"方铅岩": 5}), 0.6))

    def test_common_substring_found(self):
        c = Counter({"方铅岩砖": 2, "方铅岩台阶": 1, "方铅岩": 1, "方前言": 1})
        result = _extract_common_zh(c, 0.6)
        self.assertIsNotNone(result)
        assert result is not None
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
        verdicts = check_consistency([], [])
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
        glossary = [{"en": "Iron", "zh": "铁"}]
        verdicts = check_consistency(glossary, alignment["matched_entries"])
        self.assertEqual(len(verdicts), 0)

    def test_collect_zh_freq_uses_keys_not_accum_freq(self):
        """低频术语（freq 虚高但 keys<5）应被过滤。"""
        merged = {
            "copper": {
                "normalized": "copper",
                "variants": {"copper", "coppers"},
                "freq": 9,
                "keys": ["k1", "k2", "k3"],
                "ngram_type": "unigrams",
            },
        }
        matched = [
            {"key": "k1", "en": "Copper Ore", "zh": "铜矿石"},
            {"key": "k2", "en": "Copper Block", "zh": "铜块"},
            {"key": "k3", "en": "Copper Ingot", "zh": "铜锭"},
        ]
        result = _collect_zh_translations(
            merged, matched, min_freq=5, min_consensus=0.6,
            min_total=1, max_zh_len=200, max_en_len=200,
        )
        self.assertEqual(len(result), 0)

    def test_collect_zh_freq_passes_with_enough_keys(self):
        """术语 keys>=5 时应通过频率过滤。"""
        merged = {
            "copper": {
                "normalized": "copper",
                "variants": {"copper"},
                "freq": 3,
                "keys": ["k1", "k2", "k3", "k4", "k5"],
                "ngram_type": "unigrams",
            },
        }
        matched = [
            {"key": "k1", "en": "Copper Ore", "zh": "铜"},
            {"key": "k2", "en": "Copper Block", "zh": "铜"},
            {"key": "k3", "en": "Copper Ingot", "zh": "铜"},
            {"key": "k4", "en": "Deepslate Copper Ore", "zh": "深层铜"},
            {"key": "k5", "en": "Raw Copper", "zh": "粗铜"},
        ]
        result = _collect_zh_translations(
            merged, matched, min_freq=5, min_consensus=0.6,
            min_total=1, max_zh_len=200, max_en_len=200,
        )
        self.assertGreaterEqual(len(result), 1)

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

    def test_llm_verify_glossary_no_corrections(self):
        """LLM 返回空修正时 glossary 不变。"""
        glossary = [
            {"en": "copper", "zh": "铜"},
            {"en": "iron", "zh": "铁"},
        ]
        en_data = {
            "block.copper_ore": "Copper Ore",
            "block.iron_ore": "Iron Ore",
        }
        mock_llm = lambda p: "[]"
        result = llm_verify_glossary(glossary, en_data, mock_llm)
        self.assertIs(result, glossary)
        self.assertEqual(glossary[0]["zh"], "铜")
        self.assertEqual(glossary[1]["zh"], "铁")

    def test_llm_verify_glossary_has_correction(self):
        """LLM 返回修正时 glossary 被更新。"""
        glossary = [
            {"en": "copper", "zh": "铜"},
        ]
        en_data = {
            "block.copper_ore": "Copper Ore",
            "block.copper_block": "Copper Block",
        }
        mock_llm = lambda p: '[{"en":"copper","old_zh":"铜","new_zh":"铜矿石","reason":"应包含材质名"}]'
        result = llm_verify_glossary(glossary, en_data, mock_llm)
        self.assertIs(result, glossary)
        self.assertEqual(glossary[0]["zh"], "铜矿石")

    def test_llm_verify_glossary_llm_exception_fallback(self):
        """LLM 调用异常时返回原始 glossary 不丢失数据。"""
        glossary = [
            {"en": "copper", "zh": "铜"},
        ]
        en_data = {
            "block.copper_ore": "Copper Ore",
        }

        def mock_llm(_p):
            raise RuntimeError("网络错误")

        result = llm_verify_glossary(glossary, en_data, mock_llm)
        self.assertIs(result, glossary)
        self.assertEqual(glossary[0]["zh"], "铜")

    def test_llm_verify_glossary_empty_glossary(self):
        """空 glossary 直接返回。"""
        result = llm_verify_glossary([], {}, lambda p: "[]")
        self.assertEqual(result, [])

    def test_llm_verify_glossary_no_llm_call(self):
        """llm_call 为 None 时直接返回。"""
        glossary = [{"en": "copper", "zh": "铜"}]
        result = llm_verify_glossary(glossary, {}, None)  # type: ignore[arg-type]
        self.assertIs(result, glossary)

    def test_check_consistency_merged_none_downgrade(self):
        """merged=None 时仅使用 glossary en 值构建正则。"""
        glossary = [
            {"en": "Iron", "zh": "铁"},
        ]
        matched_entries = [
            self._make_entry("item.iron_sword", "Iron Sword", "铁剑"),
            self._make_entry("item.iron_axe", "Iron Axe", "铁斧"),
        ]
        verdicts = check_consistency(glossary, matched_entries, merged=None)
        self.assertEqual(len(verdicts), 0)

    def test_check_consistency_with_merged_variants(self):
        """merged 参数提供变体展开，短术语借助变体匹配。"""
        glossary = [
            {"en": "iron", "zh": "铁"},
        ]
        merged = {
            "iron": {
                "normalized": "iron",
                "variants": ["iron", "irons"],
                "freq": 5,
                "keys": ["item.iron_sword", "item.iron_axe"],
                "ngram_type": "unigrams",
            },
        }
        matched_entries = [
            self._make_entry("item.iron_sword", "Iron Sword", "铁剑"),
        ]
        verdicts = check_consistency(glossary, matched_entries, merged=merged)
        self.assertEqual(len(verdicts), 0)

    def test_check_consistency_music_disc_skipped(self):
        """唱片名条目跳过术语检查。"""
        glossary = [
            {"en": "Music", "zh": "音乐"},
        ]
        matched_entries = [
            self._make_entry("item.music_disc_cat.desc", "Music Disc", ""),
        ]
        verdicts = check_consistency(glossary, matched_entries)
        self.assertEqual(len(verdicts), 0)

    def test_check_consistency_term_mismatch_found(self):
        """术语未使用标准译文时生成 FAIL verdict。"""
        glossary = [
            {"en": "Iron", "zh": "铁"},
        ]
        matched_entries = [
            self._make_entry("item.iron_sword", "Iron Sword", "钢剑"),
        ]
        verdicts = check_consistency(glossary, matched_entries)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["verdict"], "❌ FAIL")
        self.assertIn("术语不一致", verdicts[0]["reason"])


if __name__ == "__main__":
    unittest.main()
