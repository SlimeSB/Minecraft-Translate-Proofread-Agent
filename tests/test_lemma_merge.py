"""测试词形归并和中文互斥救援。"""
import unittest

from src.checkers.lemma_merge import (
    raw_merge, try_rescue_short_term, _apply_merge_map,
    inflection_lemmatize_term, inflection_merge,
)


class TestRawMerge(unittest.TestCase):
    def test_basic_merge(self):
        """基本归并：同一词面的 unigram/bigram 合并频次。"""
        extracted = {
            "unigrams": [
                {"term": "sword", "freq": 3, "keys": ["k1", "k2", "k3"]},
                {"term": "shield", "freq": 2, "keys": ["k4", "k5"]},
            ],
            "bigrams": [
                {"term": "iron sword", "freq": 2, "keys": ["k6", "k7"]},
            ],
            "trigrams": [],
        }
        result = raw_merge(extracted)
        self.assertIn("sword", result)
        self.assertEqual(result["sword"]["freq"], 3)
        self.assertIn("iron sword", result)
        self.assertEqual(result["iron sword"]["freq"], 2)

    def test_case_normalization(self):
        """大小写应归一化。"""
        extracted = {
            "unigrams": [
                {"term": "Sword", "freq": 1, "keys": ["k1"]},
                {"term": "sword", "freq": 2, "keys": ["k2", "k3"]},
            ],
            "bigrams": [],
            "trigrams": [],
        }
        result = raw_merge(extracted)
        # 两个 "sword" 变体应归并
        self.assertIn("sword", result)
        self.assertEqual(result["sword"]["freq"], 3)

    def test_variants_tracked(self):
        """变体集合应被记录。"""
        extracted = {
            "unigrams": [
                {"term": "Sword", "freq": 1, "keys": ["k1"]},
                {"term": "sword", "freq": 1, "keys": ["k2"]},
            ],
            "bigrams": [],
            "trigrams": [],
        }
        result = raw_merge(extracted)
        self.assertIn("Sword", result["sword"]["variants"])
        self.assertIn("sword", result["sword"]["variants"])


class TestApplyMergeMap(unittest.TestCase):
    def test_merge_freq_equals_unique_keys(self):
        """合并两个有重叠 key 的桶后，freq 应等于去重 key 数量，而非加法累计。"""
        merged = {
            "sword": {
                "normalized": "sword",
                "variants": {"sword"},
                "freq": 5,
                "keys": ["k1", "k2", "k3", "k4", "k5"],
                "ngram_type": "unigrams",
            },
            "swords": {
                "normalized": "swords",
                "variants": {"swords"},
                "freq": 4,
                "keys": ["k3", "k4", "k5", "k6"],
                "ngram_type": "unigrams",
            },
        }
        redirect = {"swords": "sword"}
        result = _apply_merge_map(merged, redirect)
        self.assertIn("sword", result)
        self.assertEqual(result["sword"]["freq"], 6)
        self.assertEqual(len(result["sword"]["keys"]), 6)
        self.assertIn("k6", result["sword"]["keys"])

    def test_merge_no_overlap_keys(self):
        """合并两个无重叠 key 的桶后，freq 应等于两桶 key 数量之和。"""
        merged = {
            "copper": {
                "normalized": "copper",
                "variants": {"copper"},
                "freq": 3,
                "keys": ["k1", "k2", "k3"],
                "ngram_type": "unigrams",
            },
            "coppers": {
                "normalized": "coppers",
                "variants": {"coppers"},
                "freq": 2,
                "keys": ["k4", "k5"],
                "ngram_type": "unigrams",
            },
        }
        redirect = {"coppers": "copper"}
        result = _apply_merge_map(merged, redirect)
        self.assertEqual(result["copper"]["freq"], 5)
        self.assertEqual(len(result["copper"]["keys"]), 5)


class TestTryRescueShortTerm(unittest.TestCase):
    def setUp(self):
        self.merged = {
            "red apple": {
                "normalized": "red apple",
                "variants": {"red apple"},
                "freq": 3,
                "keys": ["k1", "k2", "k3"],
                "ngram_type": "bigrams",
            },
            "apple": {
                "normalized": "apple",
                "variants": {"apple"},
                "freq": 10,
                "keys": ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8", "k9", "k10"],
                "ngram_type": "unigrams",
            },
        }
        self.matched = [
            {"key": "k1", "en": "Red Apple", "zh": "红苹果"},
            {"key": "k2", "en": "Green Apple", "zh": "绿苹果"},
            {"key": "k3", "en": "Golden Apple", "zh": "金苹果"},
            {"key": "k4", "en": "Apple", "zh": "苹果"},
            {"key": "k5", "en": "Apple", "zh": "苹果"},
            {"key": "k6", "en": "Apple", "zh": "苹果"},
            {"key": "k7", "en": "Apple", "zh": "苹果"},
            {"key": "k8", "en": "Apple", "zh": "苹果"},
            {"key": "k9", "en": "Apple", "zh": "苹果"},
            {"key": "k10", "en": "Apple", "zh": "苹果"},
        ]

    def test_rescue_when_zh_differs(self):
        """当短术语在排除长术语的 key 后指向不同中文时，应救援。"""
        short = {"en": "Apple", "zh": "红苹果"}    # 当前与长术语冲突
        long = {"en": "Red Apple", "zh": "红苹果"}
        result = try_rescue_short_term(short, long, self.merged, self.matched)
        # 排除 k1/k2/k3 后，apple 仅在 k4/k5 出现，zh="苹果"
        self.assertIsNotNone(result)
        self.assertEqual(result["zh"], "苹果")

    def test_no_rescue_when_zh_same(self):
        """当短术语在排除后仍指向相同中文时，不应救援。"""
        short = {"en": "Apple", "zh": "红苹果"}
        long = {"en": "Red Apple", "zh": "红苹果"}
        matched_modified = [
            {"key": "k1", "en": "Red Apple", "zh": "红苹果"},
            {"key": "k2", "en": "Green Apple", "zh": "绿苹果"},
            {"key": "k3", "en": "Golden Apple", "zh": "金苹果"},
            {"key": "k4", "en": "Apple", "zh": "红苹果"},
            {"key": "k5", "en": "Apple", "zh": "红苹果"},
            {"key": "k6", "en": "Apple", "zh": "红苹果"},
            {"key": "k7", "en": "Apple", "zh": "红苹果"},
            {"key": "k8", "en": "Apple", "zh": "红苹果"},
            {"key": "k9", "en": "Apple", "zh": "红苹果"},
            {"key": "k10", "en": "Apple", "zh": "红苹果"},
        ]
        result = try_rescue_short_term(short, long, self.merged, matched_modified)
        self.assertIsNone(result)


class TestInflectionMerge(unittest.TestCase):
    """测试 inflection 名词单数归一化归并。"""

    def _make_bucket(self, term: str, freq: int, keys: list[str]) -> dict:
        return {
            "normalized": term,
            "variants": {term},
            "freq": freq,
            "keys": keys,
            "ngram_type": "unigrams",
        }

    def test_regular_plural_merges_to_singular(self):
        """常规复数归一：swords → sword。"""
        merged = {
            "sword": self._make_bucket("sword", 5, ["k1", "k2", "k3", "k4", "k5"]),
            "swords": self._make_bucket("swords", 3, ["k3", "k4", "k6"]),
        }
        result = inflection_merge(merged)
        self.assertIn("sword", result)
        self.assertNotIn("swords", result)
        self.assertIn("swords", result["sword"]["variants"])

    def test_regular_plural_ingot(self):
        """ingots → ingot。"""
        merged = {
            "ingot": self._make_bucket("ingot", 4, ["k1", "k2", "k3", "k4"]),
            "ingots": self._make_bucket("ingots", 2, ["k3", "k5"]),
        }
        result = inflection_merge(merged)
        self.assertIn("ingot", result)
        self.assertNotIn("ingots", result)
        self.assertEqual(result["ingot"]["freq"], 5)

    def test_axes_lemmatizes_to_axis(self):
        """inflection.singularize('axes') → 'axis'（已知行为，axe/axes 不合并为设计风险）。"""
        merged = {
            "axe": self._make_bucket("axe", 3, ["k1", "k2", "k3"]),
            "axes": self._make_bucket("axes", 2, ["k3", "k4"]),
        }
        result = inflection_merge(merged)
        self.assertIn("axe", result)
        self.assertIn("axes", result)
        self.assertEqual(len(result), 2)

    def test_leaves_lemmatizes_to_leafe(self):
        """inflection.singularize('leaves') → 'leafe'（已知行为，leaf/leaves 不合并为设计风险）。"""
        merged = {
            "leaf": self._make_bucket("leaf", 2, ["k1", "k2"]),
            "leaves": self._make_bucket("leaves", 3, ["k2", "k3", "k4"]),
        }
        result = inflection_merge(merged)
        self.assertIn("leaf", result)
        self.assertIn("leaves", result)
        self.assertEqual(len(result), 2)

    def test_irregular_plural_wolves_to_wolf(self):
        """wolves → wolf。"""
        merged = {
            "wolf": self._make_bucket("wolf", 2, ["k1", "k2"]),
            "wolves": self._make_bucket("wolves", 3, ["k2", "k3", "k4"]),
        }
        result = inflection_merge(merged)
        self.assertIn("wolf", result)
        self.assertNotIn("wolves", result)

    def test_multiword_term_each_word_normalized(self):
        """iron ingots → iron ingot。"""
        merged = {
            "iron ingot": self._make_bucket("iron ingot", 3, ["k1", "k2", "k3"]),
            "iron ingots": self._make_bucket("iron ingots", 2, ["k3", "k4"]),
        }
        result = inflection_merge(merged)
        self.assertIn("iron ingot", result)
        self.assertNotIn("iron ingots", result)

    def test_crafting_unchanged(self):
        """crafting 非规则复数，不变。"""
        merged = {
            "crafting": self._make_bucket("crafting", 5, ["k1", "k2", "k3", "k4", "k5"]),
        }
        result = inflection_merge(merged)
        self.assertIn("crafting", result)
        self.assertEqual(len(result), 1)

    def test_sheep_unchanged(self):
        """sheep 不变。"""
        merged = {
            "sheep": self._make_bucket("sheep", 3, ["k1", "k2", "k3"]),
        }
        result = inflection_merge(merged)
        self.assertIn("sheep", result)
        self.assertEqual(len(result), 1)

    def test_token_subset_guard_blocks_merge(self):
        """token 真子集守卫阻止 "upgrade adds" → "upgrade"。"""
        merged = {
            "upgrade": self._make_bucket("upgrade", 5, ["k1", "k2", "k3", "k4", "k5"]),
            "upgrade adds": self._make_bucket("upgrade adds", 2, ["k6", "k7"]),
        }
        result = inflection_merge(merged)
        self.assertIn("upgrade", result)
        self.assertIn("upgrade adds", result)
        self.assertEqual(len(result), 2)

    def test_single_member_group_not_merged(self):
        """仅 1 个成员的组不合并。"""
        merged = {
            "sword": self._make_bucket("sword", 5, ["k1", "k2", "k3", "k4", "k5"]),
            "shield": self._make_bucket("shield", 3, ["k6", "k7", "k8"]),
        }
        result = inflection_merge(merged)
        self.assertIn("sword", result)
        self.assertIn("shield", result)
        self.assertEqual(len(result), 2)

    def test_canonical_picks_highest_freq_when_lemma_absent(self):
        """原形不存在时选频次最高的做起手 canonical。"""
        merged = {
            "ingots": self._make_bucket("ingots", 4, ["k1", "k2", "k3", "k4"]),
            "ingot": self._make_bucket("ingot", 5, ["k1", "k2", "k3", "k4", "k5"]),
        }
        result = inflection_merge(merged)
        self.assertIn("ingot", result)
        self.assertNotIn("ingots", result)

    def test_no_redirect_if_lemma_not_in_merged_and_one_member(self):
        """单成员组不产生 redirect。"""
        merged = {
            "wolves": self._make_bucket("wolves", 3, ["k1", "k2", "k3"]),
        }
        result = inflection_merge(merged)
        self.assertIn("wolves", result)
        self.assertEqual(len(result), 1)


class TestInflectionLemmatizeTerm(unittest.TestCase):

    def test_single_word_plural(self):
        self.assertEqual(inflection_lemmatize_term("swords"), "sword")

    def test_single_word_singular_unchanged(self):
        self.assertEqual(inflection_lemmatize_term("sword"), "sword")

    def test_two_word_phrase(self):
        self.assertEqual(inflection_lemmatize_term("iron ingots"), "iron ingot")

    def test_three_word_phrase(self):
        self.assertEqual(inflection_lemmatize_term("iron sword blades"), "iron sword blade")

    def test_no_change_needed(self):
        self.assertEqual(inflection_lemmatize_term("crafting table"), "crafting table")

    def test_irregular_plural_leafe(self):
        self.assertEqual(inflection_lemmatize_term("leaves"), "leafe")


if __name__ == "__main__":
    unittest.main()
