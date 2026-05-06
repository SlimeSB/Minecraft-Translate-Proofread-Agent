"""测试词形归并和中文互斥救援。"""
import unittest

from src.checkers.lemma_merge import raw_merge, try_rescue_short_term


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


if __name__ == "__main__":
    unittest.main()
