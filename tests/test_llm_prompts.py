"""测试 src/llm/prompts.py —— 条目分类、筛选、prompt 构建、多段合并。"""
# pyright: reportArgumentType=false

import unittest
from unittest.mock import patch

from src.config import RE_INDEXED_KEY

from src.llm.prompts import (
    _build_batch_references,
    build_entry_block,
    build_filter_prompt,
    build_review_prompt,
    build_untranslated_prompt,
    filter_for_llm,
    is_manual_format,
    manual_format_label,
    merge_multipart_entries,
    needs_llm_review,
    should_singleton,
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
# 2.1 TestManualFormat
# ═══════════════════════════════════════════════════════════


class TestManualFormat(unittest.TestCase):
    def test_is_manual_format_known(self):
        self.assertTrue(is_manual_format("ae2guide:something/intro.md"))

    def test_is_manual_format_unknown(self):
        self.assertFalse(is_manual_format("block.copper"))
        self.assertFalse(is_manual_format("random.key"))

    def test_should_singleton_manual(self):
        self.assertTrue(should_singleton("ae2guide:something/intro.md", ""))

    def test_should_singleton_length(self):
        long_en = "x" * 2001
        self.assertTrue(should_singleton("some.long.key", long_en))

    def test_should_singleton_normal(self):
        self.assertFalse(should_singleton("block.copper", "Copper"))

    def test_manual_format_label(self):
        self.assertNotEqual(manual_format_label("ae2guide:something"), "")

    def test_manual_format_label_unknown(self):
        self.assertEqual(manual_format_label("random.key"), "")


# ═══════════════════════════════════════════════════════════
# 2.2 TestClassifyKey (向后兼容: 仅返回手册格式标签)
# ═══════════════════════════════════════════════════════════


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

    def test_short_text_no_glossary_goes_to_llm(self):
        entries = [_entry("some.key", "Hello", "你好")]
        llm_entries, auto_pass = filter_for_llm(entries, set())
        self.assertEqual(len(llm_entries), 1)
        self.assertEqual(len(auto_pass), 0)

    def test_short_text_glossary_covered_auto_pass(self):
        entries = [_entry("some.key", "Hello World", "你好世界")]
        glossary = [{"en": "Hello", "zh": "你好"}, {"en": "World", "zh": "世界"}]
        llm_entries, auto_pass = filter_for_llm(entries, set(), glossary)
        self.assertEqual(len(llm_entries), 0)
        self.assertEqual(len(auto_pass), 1)

    def test_short_text_glossary_not_covered_goes_to_llm(self):
        entries = [_entry("some.key", "Hello World", "你好世界")]
        glossary = [{"en": "Hello", "zh": "你好"}]
        llm_entries, auto_pass = filter_for_llm(entries, set(), glossary)
        self.assertEqual(len(llm_entries), 1)
        self.assertEqual(len(auto_pass), 0)

    def test_mixed_scenarios(self):
        entries = [
            _entry("flagged.key", "Hello", "你好"),
            _entry("long.key", "x" * 81, "y" * 10),
            _entry("short.key", "Hi", "嗨"),
        ]
        auto_flagged = {"flagged.key"}
        llm_entries, auto_pass = filter_for_llm(entries, auto_flagged)
        self.assertEqual(len(llm_entries), 3)
        self.assertEqual(len(auto_pass), 0)

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
        self.assertIn("### 术语表", prompts[0])
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
        self.assertIn("### 模糊匹配", prompts[0])
        self.assertIn("88.5", prompts[0])

    def test_ae2guide_batch_size_one(self):
        entries = [_entry("ae2guide:doc1", "D1", "文1"), _entry("ae2guide:doc2", "D2", "文2")]
        prompts = build_review_prompt(entries, batch_size=25)
        self.assertEqual(len(prompts), 2)

    def test_shared_prefix_across_batches(self):
        entries = self._entries(55)
        prompts = build_review_prompt(entries, batch_size=25)
        self.assertGreaterEqual(len(prompts), 2)
        for p in prompts:
            self.assertIn("key:", p, "Each prompt should contain entry blocks")

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

    def test_long_text_preserved_in_full(self):
        long_old_en = "A" * 500
        entry = {"key": "block.iron", "en": "Iron", "zh": "铁",
                  "_change": {"old_en": long_old_en, "old_zh": "旧铁"}}
        block = build_entry_block(entry)
        self.assertIn(long_old_en, block)
        self.assertIn("旧铁", block)


class TestBuildBatchReferences(unittest.TestCase):
    def test_empty_returns_empty(self):
        result = _build_batch_references([])
        self.assertEqual(result, "")

    def test_glossary_section(self):
        entries = [_entry("block.copper", "Copper Ore", "铜矿石")]
        glossary = [{"en": "Copper", "zh": "铜"}, {"en": "Ore", "zh": "矿石"}]
        result = _build_batch_references(entries, glossary=glossary)
        self.assertIn("### 术语表", result)
        self.assertIn('"Copper" → "铜"', result)
        self.assertIn('"Ore" → "矿石"', result)

    def test_glossary_dedup_by_lowercase(self):
        entries = [_entry("key1", "Copper copper", "铜")]
        glossary = [{"en": "Copper", "zh": "铜"}, {"en": "copper", "zh": "铜"}]
        result = _build_batch_references(entries, glossary=glossary)
        self.assertEqual(result.count('"Copper"'), 1)

    def test_fuzzy_section(self):
        entries = [_entry("block.copper", "Copper", "铜")]
        fuzzy_map = {
            "block.copper": [
                {"similarity": 88.5, "key": "block.iron", "en": "Iron", "zh": "铁"}
            ]
        }
        result = _build_batch_references(entries, fuzzy_map=fuzzy_map)
        self.assertIn("### 模糊匹配", result)
        self.assertIn("88.5", result)
        self.assertIn("Iron", result)

    def test_fuzzy_only_matching_keys(self):
        entries = [_entry("block.copper", "Copper", "铜")]
        fuzzy_map = {
            "other.key": [{"similarity": 90.0, "key": "x", "en": "X", "zh": "X"}]
        }
        result = _build_batch_references(entries, fuzzy_map=fuzzy_map)
        self.assertNotIn("### 模糊匹配", result)

    def test_all_empty_returns_empty(self):
        result = _build_batch_references([], glossary=None, fuzzy_map={}, dict_stores=[])
        self.assertEqual(result, "")


# ═══════════════════════════════════════════════════════════
# TestVanillaTermsStore
# ═══════════════════════════════════════════════════════════


class TestVanillaTermsStore(unittest.TestCase):
    def setUp(self):
        import tempfile
        sqlite3 = __import__("sqlite3")
        self._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmpfile.close()
        self._db_path = self._tmpfile.name
        conn = sqlite3.connect(self._db_path)
        conn.execute("CREATE TABLE terms (en TEXT, zh TEXT, scope TEXT, labels TEXT)")
        conn.execute(
            "INSERT INTO terms VALUES "
            "('[\"Absorption\"]', '[\"伤害吸收\"]', NULL, '[\"effect\"]'),"
            "('[\"Armor\"]', '[\"护甲\", \"护甲值\"]', NULL, '[]'),"
            "('[\"Beetroot\", \"Beetroots\"]', '[\"甜菜根\", \"甜菜\"]', NULL, '[\"food\"]'),"
            "('[\"Armor\"]', '[\"护甲值\"]', '{\"key\": \"^attribute\"}', '[]'),"
            "('[\"Cotton\"]', '[\"棉花\"]', '{\"version\": \"1.12.2\"}', '[]'),"
            "('[\"Ab\"]', '[\"短\"]', NULL, '[]')"
        )
        conn.commit()
        conn.close()
        from src.dictionary.vanilla_terms import VanillaTermsStore
        self.store = VanillaTermsStore(self._db_path)
        self.store.load()

    def tearDown(self):
        self.store.close()
        import os
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def test_basic_lookup(self):
        result = self.store.lookup("Absorption", entry_key="effect.minecraft.absorption")
        self.assertIn("伤害吸收", result)
        self.assertIn("[effect]", result)

    def test_multi_zh_format(self):
        result = self.store.lookup("Armor")
        self.assertIn("护甲 / 护甲值", result)

    def test_multi_en_format(self):
        result = self.store.lookup("Beetroot")
        self.assertIn("Beetroot / Beetroots", result)

    def test_scope_key_matches(self):
        result = self.store.lookup("Armor", entry_key="attribute.armor")
        self.assertIn("护甲值", result)

    def test_scope_key_no_match(self):
        result = self.store.lookup("Armor", entry_key="block.armor")
        self.assertTrue("护甲值" not in result or '"护甲值"' not in result.split('"护甲"')[0])

    def test_scope_version_match(self):
        result = self.store.lookup("Cotton", version="1.12.2")
        self.assertIn("棉花", result)

    def test_scope_version_no_match(self):
        result = self.store.lookup("Cotton", version="1.21")
        self.assertNotIn("棉花", result)

    def test_label_display(self):
        result = self.store.lookup("Absorption")
        self.assertIn("[effect]", result)

    def test_multi_label_display(self):
        result = self.store.lookup("Beetroot")
        self.assertIn("[food]", result)

    def test_no_label_no_bracket(self):
        result = self.store.lookup("Ab")
        self.assertNotIn("[", result)
        self.assertNotIn("]", result)

    def test_empty_query_returns_empty(self):
        result = self.store.lookup("")
        self.assertEqual(result, "")

    def test_no_match_returns_empty(self):
        result = self.store.lookup("XYZNotFoundTerm")
        self.assertEqual(result, "")


# ═══════════════════════════════════════════════════════════
# 2.5 Batch 隔离：三元组分组
# ═══════════════════════════════════════════════════════════

from src.llm.prompts import _group_by_slug_ver_ns


class TestBatchIsolation(unittest.TestCase):
    def _e(self, key, slug="", ver="", ns=""):
        return {"key": key, "en": key, "zh": key, "slug": slug, "version": ver, "namespace": ns}

    def test_same_slug_ver_ns_grouped_together(self):
        entries = [
            self._e("item.a", "ironchest", "1.21", "ironchest"),
            self._e("item.b", "ironchest", "1.21", "ironchest"),
        ]
        groups = _group_by_slug_ver_ns(entries)
        self.assertEqual(len(groups), 1)
        key = ("ironchest", "1.21", "ironchest")
        self.assertEqual(len(groups[key]), 2)

    def test_different_slug_separated(self):
        entries = [
            self._e("item.a", "ironchest", "1.21", "ironchest"),
            self._e("item.b", "create", "1.21", "create"),
        ]
        groups = _group_by_slug_ver_ns(entries)
        self.assertEqual(len(groups), 2)

    def test_same_slug_different_version_separated(self):
        entries = [
            self._e("item.a", "ironchest", "1.21", "ironchest"),
            self._e("item.b", "ironchest", "1.20.1", "ironchest"),
        ]
        groups = _group_by_slug_ver_ns(entries)
        self.assertEqual(len(groups), 2)

    def test_same_slug_ver_different_ns_separated(self):
        entries = [
            self._e("item.a", "ironchest", "1.21", "ironchest"),
            self._e("item.b", "ironchest", "1.21", "ironchest_addon"),
        ]
        groups = _group_by_slug_ver_ns(entries)
        self.assertEqual(len(groups), 2)

    def test_no_slug_ver_ns_still_works(self):
        entries = [
            self._e("item.a"),
            self._e("item.b"),
        ]
        groups = _group_by_slug_ver_ns(entries)
        self.assertEqual(len(groups), 1)

    def test_build_review_prompt_batch_isolation(self):
        """验证 build_review_prompt 不跨 slug/ver/ns。"""
        entries = [
            {"key": "item.a", "en": "A", "zh": "甲", "slug": "mod_a", "version": "1.21", "namespace": "mod_a"},
            {"key": "item.b", "en": "B", "zh": "乙", "slug": "mod_b", "version": "1.21", "namespace": "mod_b"},
        ]
        prompts = build_review_prompt(entries, batch_size=25)
        self.assertEqual(len(prompts), 2)
        self.assertIn("item.a", prompts[0])
        self.assertIn("item.b", prompts[1])


if __name__ == "__main__":
    unittest.main()
