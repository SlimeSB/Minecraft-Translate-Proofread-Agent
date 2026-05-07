"""测试术语提取模块。"""
import unittest

from src.tools.terminology_extract import extract_terms, tokenize, STOP_WORDS


class TestTokenize(unittest.TestCase):
    def test_basic_words(self):
        self.assertEqual(tokenize("Iron Sword"), ["iron", "sword"])

    def test_strip_format_codes(self):
        """去除 Minecraft 格式码。"""
        tokens = tokenize("§6Gold §cRed")
        self.assertEqual(tokens, ["gold", "red"])

    def test_strip_html(self):
        """去除 HTML 标签。"""
        tokens = tokenize("<red>Danger</red>")
        self.assertEqual(tokens, ["danger"])

    def test_strip_printf(self):
        """去除 printf 占位符。"""
        tokens = tokenize("HP: %d / %d")
        self.assertEqual(tokens, ["hp"])

    def test_lowercase(self):
        """分词结果应全小写。"""
        tokens = tokenize("Iron SWORD")
        self.assertEqual(tokens, ["iron", "sword"])

    def test_empty_string(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("%d"), [])


class TestExtractTerms(unittest.TestCase):
    def test_unigrams(self):
        """基本 unigram 提取。"""
        en = {
            "item.apple": "Red Apple",
            "item.golden_apple": "Golden Apple",
            "block.stone": "Stone Block",
        }
        result = extract_terms(en, min_freq=2, max_ngram=1)
        # "apple" 出现在两条，"red"/"golden"/"stone"/"block" 各一次
        unigrams = {u["term"]: u["freq"] for u in result["unigrams"]}
        self.assertEqual(unigrams.get("apple"), 2)

    def test_bigrams(self):
        """bigram 提取。"""
        en = {
            "item.red_apple": "Red Apple",
            "item.golden_apple": "Golden Apple",
        }
        result = extract_terms(en, min_freq=1, max_ngram=2)
        bigrams = {b["term"]: b["freq"] for b in result["bigrams"]}
        # "golden apple" 和 "red apple" 各出现一次，共享 "apple" unigram
        self.assertIn("red apple", bigrams)
        self.assertIn("golden apple", bigrams)

    def test_min_freq_filter(self):
        """低频词应被过滤。"""
        en = {
            "a": "Red Apple",
            "b": "Golden Apple",
            "c": "Unique Term",
        }
        result = extract_terms(en, min_freq=2, max_ngram=1)
        unigrams = {u["term"] for u in result["unigrams"]}
        self.assertIn("apple", unigrams)
        self.assertNotIn("unique", unigrams)  # freq=1, filtered

    def test_stop_words_filtered(self):
        """stop words 应被过滤。"""
        en = {"a": "the block of gold"}
        result = extract_terms(en, min_freq=1, max_ngram=1)
        unigrams = {u["term"] for u in result["unigrams"]}
        self.assertNotIn("the", unigrams)
        self.assertNotIn("of", unigrams)
        self.assertIn("gold", unigrams)

    def test_empty_input(self):
        """空输入。"""
        result = extract_terms({}, min_freq=1, max_ngram=3)
        self.assertEqual(len(result["unigrams"]), 0)
        self.assertEqual(len(result["bigrams"]), 0)
        self.assertEqual(len(result["trigrams"]), 0)

    def test_keys_included(self):
        """每条术语应包含来源 key 列表。"""
        en = {"item.apple": "Red Apple", "item.stone": "Stone"}
        result = extract_terms(en, min_freq=1, max_ngram=1)
        for u in result["unigrams"]:
            self.assertIn("keys", u)
            self.assertIsInstance(u["keys"], list)


if __name__ == "__main__":
    unittest.main()
