"""测试模糊搜索模块的纯函数。"""
import unittest

from src.tools.fuzzy_search import levenshtein_distance, calc_similarity


class TestLevenshtein(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(levenshtein_distance("hello", "hello"), 0)

    def test_single_insert(self):
        self.assertEqual(levenshtein_distance("helo", "hello"), 1)

    def test_single_delete(self):
        self.assertEqual(levenshtein_distance("hello", "helo"), 1)

    def test_single_substitute(self):
        self.assertEqual(levenshtein_distance("hello", "hallo"), 1)

    def test_empty_strings(self):
        self.assertEqual(levenshtein_distance("", ""), 0)
        self.assertEqual(levenshtein_distance("abc", ""), 3)
        self.assertEqual(levenshtein_distance("", "abc"), 3)

    def test_case_sensitive(self):
        self.assertEqual(levenshtein_distance("Hello", "hello"), 1)

    def test_completely_different(self):
        self.assertEqual(levenshtein_distance("abc", "xyz"), 3)


class TestCalcSimilarity(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(calc_similarity("hello", "hello"), 100.0)

    def test_half_similar(self):
        sim = calc_similarity("abc", "abd")
        self.assertAlmostEqual(sim, 66.67, places=1)

    def test_completely_different(self):
        self.assertEqual(calc_similarity("abc", "xyz"), 0.0)

    def test_empty_strings(self):
        self.assertEqual(calc_similarity("", ""), 0.0)
        self.assertEqual(calc_similarity("abc", ""), 0.0)
        self.assertEqual(calc_similarity("", "abc"), 0.0)

    def test_different_lengths(self):
        sim = calc_similarity("abc", "abcdef")
        self.assertAlmostEqual(sim, 50.0, places=1)


if __name__ == "__main__":
    unittest.main()
