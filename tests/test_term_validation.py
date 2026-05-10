"""测试共享术语验证模块。"""
import unittest

from src.tools.term_validation import STOP_WORDS, is_valid_term


class TestStopWords(unittest.TestCase):
    def test_stop_words_is_set(self):
        self.assertIsInstance(STOP_WORDS, set)

    def test_stop_words_loaded_from_config(self):
        self.assertIn("the", STOP_WORDS)
        self.assertIn("a", STOP_WORDS)
        self.assertIn("an", STOP_WORDS)
        self.assertIn("of", STOP_WORDS)
        self.assertIn("to", STOP_WORDS)
        self.assertIn("is", STOP_WORDS)
        self.assertIn("it", STOP_WORDS)
        self.assertIn("in", STOP_WORDS)
        self.assertIn("on", STOP_WORDS)
        self.assertIn("at", STOP_WORDS)
        self.assertIn("be", STOP_WORDS)


class TestIsValidTerm(unittest.TestCase):
    def test_valid_normal_word(self):
        self.assertTrue(is_valid_term("crafting"))
        self.assertTrue(is_valid_term("redstone"))
        self.assertTrue(is_valid_term("crafting table"))

    def test_too_short(self):
        self.assertFalse(is_valid_term("ab"))
        self.assertFalse(is_valid_term("a"))
        self.assertFalse(is_valid_term(""))

    def test_contains_digits(self):
        self.assertFalse(is_valid_term("tier3"))
        self.assertFalse(is_valid_term("version2"))
        self.assertFalse(is_valid_term("block_1"))

    def test_pure_symbols(self):
        self.assertFalse(is_valid_term("123"))
        self.assertFalse(is_valid_term("1.5"))
        self.assertFalse(is_valid_term("test_1"))
        self.assertFalse(is_valid_term("1-2"))

    def test_stop_word_global(self):
        """精确命中停用词应被过滤。"""
        self.assertFalse(is_valid_term("the"))
        self.assertFalse(is_valid_term("of"))
        self.assertFalse(is_valid_term("in"))

    def test_multiword_with_stop_component(self):
        """多词短语中任一成分是停用词应被过滤。"""
        self.assertFalse(is_valid_term("block of gold"))
        self.assertFalse(is_valid_term("the crafting table"))

    def test_strip_whitespace(self):
        """前后空格应被去除。"""
        self.assertTrue(is_valid_term("  crafting  "))

    def test_case_insensitive(self):
        """大小写不敏感。"""
        self.assertFalse(is_valid_term("THE"))
        self.assertFalse(is_valid_term("Block Of Gold"))

    def test_valid_compound(self):
        """正常复合术语应通过。"""
        self.assertTrue(is_valid_term("iron ingot"))
        self.assertTrue(is_valid_term("nether quartz ore"))
        self.assertTrue(is_valid_term("diamond sword"))

    def test_none_or_empty(self):
        self.assertFalse(is_valid_term(""))
        self.assertFalse(is_valid_term("   "))


if __name__ == "__main__":
    unittest.main()
