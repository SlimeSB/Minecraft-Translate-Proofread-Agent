"""测试 src/llm/prompts.py —— 条目分类、筛选、prompt 构建、多段合并。"""
# pyright: reportArgumentType=false

import unittest
from unittest.mock import patch

from src.config import RE_INDEXED_KEY

from src.llm.prompts import (
    build_entry_block,
    build_filter_prompt,
    build_review_prompt,
    build_untranslated_prompt,
    classify_entries,
    classify_key,
    filter_for_llm,
    group_prefix,
    merge_multipart_entries,
    needs_llm_review,
)


def _entry(key, en="", zh=""):
    return {"key": key, "en": en, "zh": zh}


def _verdict(key, en_current="", zh_current="", verdict="⚠️ SUGGEST", reason="", suggestion=""):
    return {
        "key": key,
        "en_current": en_current,
        "zh_current": zh_current,
        "verdict": verdict,
        "reason": reason,
        "suggestion": suggestion,
    }


# ═══════════════════════════════════════════════════════════
# 2.1 TestClassifyEntries
# ═══════════════════════════════════════════════════════════


class TestClassifyEntries(unittest.TestCase):
    def test_group_by_prefix(self):
        entries = [
            _entry("advancements.foo", "Adv Foo", "进度Foo"),
            _entry("block.bar", "Block Bar", "方块Bar"),
            _entry("ae2guide:doc", "Doc", "文档"),
        ]
        groups = classify_entries(entries)
        self.assertIn("advancements.", groups)
        self.assertIn("block.", groups)
        self.assertIn("ae2guide:", groups)
        self.assertEqual(len(groups), 3)

    def test_ae2guide_prefix_isolation(self):
        entries = [_entry("ae2guide:guide.doc", "Guide", "指南")]
        groups = classify_entries(entries)
        self.assertIn("ae2guide:", groups)

    def test_unmatched_goes_to_default(self):
        entries = [_entry("random.unmatched.key", "Rand", "兰")]
        groups = classify_entries(entries)
        self.assertIn("__default__", groups)
        self.assertEqual(len(groups), 1)

    def test_multiple_entries_same_prefix(self):
        entries = [_entry("block.copper", "Copper", "铜"), _entry("block.iron", "Iron", "铁")]
        groups = classify_entries(entries)
        self.assertIn("block.", groups)
        self.assertEqual(len(groups["block."]), 2)

    def test_longest_prefix_match(self):
        entries = [_entry("block.mod.copper", "MC", "我的世界")]
        groups = classify_entries(entries)
        self.assertIn("block.", groups)


# ═══════════════════════════════════════════════════════════
# 2.2 TestClassifyKey
# ═══════════════════════════════════════════════════════════


class TestClassifyKey(unittest.TestCase):
    def test_known_prefix_returns_label(self):
        self.assertNotEqual(classify_key("block.copper"), "其他")

    def test_unknown_key_returns_default(self):
        self.assertEqual(classify_key("no.such.prefix.here"), "其他")

    def test_ae2guide_key(self):
        result = classify_key("ae2guide:something")
        self.assertNotEqual(result, "其他")

    def test_group_prefix_longest_match(self):
        self.assertEqual(group_prefix("advancements.test"), "advancements.")
        self.assertEqual(group_prefix("death.attack.mob"), "death.")


# ═══════════════════════════════════════════════════════════
# 2.3 TestFilterForLlm
# ═══════════════════════════════════════════════════════════


class TestFilterForLlm(unittest.TestCase):
    def test_auto_flagged_entries_sent_to_llm(self):
        entries = [_entry("some.key", "Hello", "你好")]
        auto_flagged = {"some.key"}
        llm_entries, auto_pass = filter_for_llm(entries, auto_flagged)
        self.assertEqual(len(llm_entries), 1)
        self.assertEqual(len(auto_pass), 0)
        self.assertEqual(llm_entries[0]["key"], "some.key")

    def test_long_text_sent_to_llm(self):
        long_en = "x" * 81
        entries = [_entry("some.key", long_en, "译文")]
        llm_entries, auto_pass = filter_for_llm(entries, set())
        self.assertEqual(len(llm_entries), 1)

    def test_short_text_no_flag_skipped(self):
        entries = [_entry("some.key", "Hello", "你好")]
        llm_entries, auto_pass = filter_for_llm(entries, set())
        self.assertEqual(len(llm_entries), 0)
        self.assertEqual(len(auto_pass), 1)

    def test_mixed_scenarios(self):
        entries = [
            _entry("flagged.key", "Hello", "你好"),
            _entry("long.key", "x" * 81, "y" * 10),
            _entry("short.key", "Hi", "嗨"),
        ]
        auto_flagged = {"flagged.key"}
        llm_entries, auto_pass = filter_for_llm(entries, auto_flagged)
        self.assertEqual(len(llm_entries), 2)
        self.assertEqual(len(auto_pass), 1)
        self.assertEqual(auto_pass[0]["key"], "short.key")

    def test_needs_llm_review_desc_suffix(self):
        self.assertTrue(needs_llm_review(_entry("item.desc", "Desc", "描述")))
        self.assertTrue(needs_llm_review(_entry("block.description", "Desc", "描述")))
        self.assertTrue(needs_llm_review(_entry("item.flavor.title", "Title", "标题")))


# ═══════════════════════════════════════════════════════════
# 2.4 TestMergeMultipartEntries
# ═══════════════════════════════════════════════════════════


class TestMergeMultipartEntries(unittest.TestCase):
    def test_consecutive_numbered_suffix_merged(self):
        entries = [
            _entry("book.page.0", "Page0", "页0"),
            _entry("book.page.1", "Page1", "页1"),
            _entry("book.page.2", "Page2", "页2"),
        ]
        merged = merge_multipart_entries(entries)
        self.assertIn("book.page.0", merged)
        self.assertIn("book.page.1", merged)
        self.assertIn("book.page.2", merged)
        full_en, full_zh = merged["book.page.0"]
        self.assertEqual(full_en, "Page0Page1Page2")
        self.assertEqual(full_zh, "页0页1页2")

    def test_single_entries_not_merged(self):
        entries = [_entry("block.copper", "Copper", "铜"), _entry("block.iron", "Iron", "铁")]
        merged = merge_multipart_entries(entries)
        self.assertEqual(len(merged), 0)

    def test_single_numbered_entry_not_merged(self):
        entries = [_entry("item.desc.0", "Desc", "描述")]
        merged = merge_multipart_entries(entries)
        self.assertEqual(len(merged), 0)

    def test_bracket_numbered_suffix(self):
        entries = [
            _entry("tag[0]", "A", "甲"),
            _entry("tag[1]", "B", "乙"),
        ]
        merged = merge_multipart_entries(entries)
        self.assertIn("tag[0]", merged)
        full_en, full_zh = merged["tag[0]"]
        self.assertEqual(full_en, "AB")

    def test_re_multipart_pattern(self):
        self.assertTrue(RE_INDEXED_KEY.match("book.page.0"))
        self.assertTrue(RE_INDEXED_KEY.match("tag[5]"))
        self.assertIsNone(RE_INDEXED_KEY.match("block.copper"))


# ═══════════════════════════════════════════════════════════
# 2.5 TestBuildReviewPrompt
# ═══════════════════════════════════════════════════════════


class TestBuildReviewPrompt(unittest.TestCase):
    def _entries(self, count, prefix="block."):
        return [_entry(f"{prefix}item{i}", f"EN {i}", f"ZH {i}") for i in range(count)]

    def test_single_batch_within_limit(self):
        entries = self._entries(5)
        prompts = build_review_prompt(entries, batch_size=25)
        self.assertEqual(len(prompts), 1)

    def test_multi_batch_split(self):
        entries = self._entries(55)
        prompts = build_review_prompt(entries, batch_size=25)
        self.assertEqual(len(prompts), 3)

    def test_prompt_contains_glossary_terms(self):
        entry = _entry("block.copper", "Copper Ore", "铜矿石")
        glossary = [{"en": "Copper", "zh": "铜"}, {"en": "Ore", "zh": "矿石"}]
        auto_map = {}
        fuzzy_map = {}
        prompts = build_review_prompt([entry], glossary, auto_map, fuzzy_map, 25)
        self.assertIn("铜", prompts[0])
        self.assertIn("Copper", prompts[0])

    def test_prompt_contains_auto_verdict_info(self):
        entry = _entry("block.copper", "Copper", "铜")
        auto_map = {"block.copper": [_verdict("block.copper", verdict="❌ FAIL", reason="占位符")]}
        prompts = build_review_prompt([entry], None, auto_map, None, 25)
        self.assertIn("❌ FAIL", prompts[0])

    def test_prompt_contains_fuzzy_info(self):
        entry = _entry("block.copper", "Copper", "铜")
        fuzzy_map = {"block.copper": [{"similarity": 88.5, "key": "block.iron", "en": "Iron", "zh": "铁"}]}
        prompts = build_review_prompt([entry], None, None, fuzzy_map, 25)
        self.assertIn("88.5", prompts[0])

    def test_ae2guide_batch_size_one(self):
        entries = [_entry("ae2guide:doc1", "D1", "文1"), _entry("ae2guide:doc2", "D2", "文2")]
        prompts = build_review_prompt(entries, batch_size=25)
        self.assertEqual(len(prompts), 2)

    def test_empty_entries_returns_empty(self):
        prompts = build_review_prompt([])
        self.assertEqual(len(prompts), 0)


# ═══════════════════════════════════════════════════════════
# 2.6 TestBuildUntranslatedPrompt
# ═══════════════════════════════════════════════════════════


class TestBuildUntranslatedPrompt(unittest.TestCase):
    def test_prompt_contains_entry_keys(self):
        entries = [_entry("test.key", "Hello", "Hello")]
        prompts = build_untranslated_prompt(entries, batch_size=1)
        self.assertIn("test.key", prompts[0])
        self.assertIn("Hello", prompts[0])

    def test_batch_split(self):
        entries = [_entry(f"key{i}", f"Val{i}", f"Val{i}") for i in range(3)]
        prompts = build_untranslated_prompt(entries, batch_size=2)
        self.assertEqual(len(prompts), 2)

    def test_empty_entries_returns_empty(self):
        prompts = build_untranslated_prompt([])
        self.assertEqual(len(prompts), 0)


# ═══════════════════════════════════════════════════════════
# 2.7 TestBuildFilterPrompt
# ═══════════════════════════════════════════════════════════


class TestBuildFilterPrompt(unittest.TestCase):
    def test_prompt_contains_key_verdict_reason(self):
        verdicts = [_verdict("block.copper", "Copper", "铜", "⚠️ SUGGEST", "术语不一致")]
        prompts = build_filter_prompt(verdicts, batch_size=2)
        self.assertIn("block.copper", prompts[0])
        self.assertIn("⚠️ SUGGEST", prompts[0])
        self.assertIn("术语不一致", prompts[0])

    def test_batch_split(self):
        verdicts = [_verdict(f"block.item{i}", f"EN{i}", f"ZH{i}", "⚠️ SUGGEST", "原因") for i in range(3)]
        prompts = build_filter_prompt(verdicts, batch_size=2)
        self.assertEqual(len(prompts), 2)

    def test_ae2guide_batch_size_one(self):
        verdicts = [
            _verdict("ae2guide:doc1", "D1", "W1", "⚠️ SUGGEST", "问题"),
            _verdict("ae2guide:doc2", "D2", "W2", "⚠️ SUGGEST", "问题"),
        ]
        prompts = build_filter_prompt(verdicts, batch_size=25)
        self.assertEqual(len(prompts), 2)

    def test_empty_verdicts_returns_empty(self):
        prompts = build_filter_prompt([])
        self.assertEqual(len(prompts), 0)

    def test_prompt_contains_suggestion(self):
        verdicts = [_verdict("test.key", "EN", "ZH", "⚠️ SUGGEST", "问题", "建议翻译")]
        prompts = build_filter_prompt(verdicts, batch_size=5)
        self.assertIn("建议翻译", prompts[0])


# ═══════════════════════════════════════════════════════════
# Build entry block
# ═══════════════════════════════════════════════════════════


class TestBuildEntryBlock(unittest.TestCase):
    def test_basic_block(self):
        entry = _entry("block.test", "Copper Block", "铜方块")
        block = build_entry_block(entry)
        self.assertIn("block.test", block)
        self.assertIn("Copper Block", block)

    def test_block_with_fuzzy_results(self):
        entry = _entry("block.test", "Copper", "铜")
        fuzzy = [{"similarity": 90.0, "en": "Copper Ore", "zh": "铜矿石", "key": "other.key"}]
        block = build_entry_block(entry, fuzzy_results=fuzzy)
        self.assertIn("90.0", block)

    def test_block_with_auto_verdicts(self):
        entry = _entry("block.test", "Copper", "铜")
        auto = [_verdict("block.test", verdict="❌ FAIL", reason="缺少占位符")]
        block = build_entry_block(entry, auto_verdicts=auto)
        self.assertIn("❌ FAIL", block)

    def test_block_with_full_context(self):
        entry = _entry("book.page.0", "Short", "短")
        block = build_entry_block(entry, full_en="FullEN0FullEN1", full_zh="FullZH0FullZH1")
        self.assertIn("FullEN0", block)
        self.assertIn("完整上下文", block)


if __name__ == "__main__":
    unittest.main()
