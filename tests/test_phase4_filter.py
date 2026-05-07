"""测试 Phase 4 过滤 — 缓存键生成与 DB 写入逻辑。"""
import unittest

from src.pipeline.phase4_filter import _cache_key


class TestCacheKey(unittest.TestCase):

    def test_deterministic(self):
        v = {"key": "item.sword", "verdict": "❌ FAIL", "reason": "bad", "zh_current": "剑"}
        self.assertEqual(_cache_key(v), _cache_key(v))

    def test_different_key_different_hash(self):
        a = {"key": "a", "verdict": "PASS", "reason": "", "zh_current": ""}
        b = {"key": "b", "verdict": "PASS", "reason": "", "zh_current": ""}
        self.assertNotEqual(_cache_key(a), _cache_key(b))

    def test_different_verdict_different_hash(self):
        a = {"key": "x", "verdict": "❌ FAIL", "reason": "", "zh_current": ""}
        b = {"key": "x", "verdict": "PASS", "reason": "", "zh_current": ""}
        self.assertNotEqual(_cache_key(a), _cache_key(b))

    def test_different_reason_different_hash(self):
        a = {"key": "x", "verdict": "PASS", "reason": "r1", "zh_current": ""}
        b = {"key": "x", "verdict": "PASS", "reason": "r2", "zh_current": ""}
        self.assertNotEqual(_cache_key(a), _cache_key(b))

    def test_zh_current_same_first_150_chars(self):
        prefix = "剑" * 150
        a = {"key": "x", "verdict": "PASS", "reason": "", "zh_current": prefix + "extra1"}
        b = {"key": "x", "verdict": "PASS", "reason": "", "zh_current": prefix + "extra2"}
        self.assertEqual(_cache_key(a), _cache_key(b))

    def test_empty_zh_current(self):
        key = _cache_key({"key": "x", "verdict": "PASS", "reason": "", "zh_current": ""})
        self.assertIsInstance(key, str)

    def test_hex_output(self):
        key = _cache_key({"key": "a", "verdict": "PASS", "reason": "", "zh_current": ""})
        self.assertEqual(len(key), 16)
        int(key, 16)


if __name__ == "__main__":
    unittest.main()
