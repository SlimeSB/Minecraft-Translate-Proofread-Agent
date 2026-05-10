"""测试 src/llm/bridge.py —— 响应解析、异步批处理、LLMBridge 方法。"""
# pyright: reportArgumentType=false

import asyncio
import json
import unittest

from src.llm.bridge import (
    LLMBridge,
    _batch_process,
    _is_truncated_json,
    _llm_call_with_retry,
    _normalize_verdict,
    parse_review_response,
)


# ═══════════════════════════════════════════════════════════
# 1.1 TestParseReviewResponse
# ═══════════════════════════════════════════════════════════


class TestParseReviewResponse(unittest.TestCase):
    def test_direct_json_array(self):
        response = '[{"key":"a.b","verdict":"PASS","reason":""}]'
        results = parse_review_response(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], "a.b")
        self.assertEqual(results[0]["verdict"], "PASS")

    def test_wrapped_structure(self):
        response = '{"verdicts": [{"key":"a.b","verdict":"FAIL"}]}'
        results = parse_review_response(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["verdict"], "FAIL")

    def test_regex_extract_embedded_array(self):
        response = '\u4e00\u4e9b\u6587\u5b57 [{"key":"a.b","verdict":"PASS"}] \u66f4\u591a\u6587\u5b57'
        results = parse_review_response(response)
        self.assertEqual(len(results), 1)

    def test_invalid_json_returns_empty(self):
        results = parse_review_response("not json at all")
        self.assertEqual(results, [])

    def test_line_by_line_json_objects(self):
        response = '{"key": "a.b", "verdict": "PASS"}\n{"key": "c.d", "verdict": "FAIL"}'
        results = parse_review_response(response)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["key"], "a.b")
        self.assertEqual(results[1]["key"], "c.d")


# ═══════════════════════════════════════════════════════════
# 1.2 TestIsTruncatedJson
# ═══════════════════════════════════════════════════════════


class TestIsTruncatedJson(unittest.TestCase):
    def test_unbalanced_braces_is_truncated(self):
        self.assertTrue(_is_truncated_json('[{"key":"a.b","value'))

    def test_balanced_braces_not_truncated(self):
        self.assertFalse(_is_truncated_json('[{"key":"a.b","verdict":"PASS"}]'))

    def test_empty_string_not_truncated(self):
        self.assertFalse(_is_truncated_json(""))

    def test_unbalanced_brackets(self):
        self.assertTrue(_is_truncated_json('[{"key":"a"},{"key":"b"'))

    def test_nested_braces_balanced(self):
        self.assertFalse(_is_truncated_json('{"a":{"b":"c"},"d":"e"}'))


# ═══════════════════════════════════════════════════════════
# 1.3 TestNormalizeVerdict
# ═══════════════════════════════════════════════════════════


class TestNormalizeVerdict(unittest.TestCase):
    def test_string_field_preserved(self):
        v = {"key": "a", "reason": "\u672f\u8bed\u4e0d\u4e00\u81f4", "verdict": "PASS"}
        _normalize_verdict(v)
        self.assertEqual(v["reason"], "\u672f\u8bed\u4e0d\u4e00\u81f4")

    def test_dict_field_extract_zh(self):
        v = {"key": "a", "suggestion": {"zh": "\u94dc\u77ff\u77f3"}, "verdict": "PASS"}
        _normalize_verdict(v)
        self.assertEqual(v["suggestion"], "\u94dc\u77ff\u77f3")

    def test_dict_field_extract_text(self):
        v = {"key": "a", "suggestion": {"text": "text_val"}, "verdict": "PASS"}
        _normalize_verdict(v)
        self.assertEqual(v["suggestion"], "text_val")

    def test_dict_field_extract_value(self):
        v = {"key": "a", "suggestion": {"value": "val_val"}, "verdict": "PASS"}
        _normalize_verdict(v)
        self.assertEqual(v["suggestion"], "val_val")

    def test_dict_field_no_zh_key_serializes(self):
        v = {"key": "a", "suggestion": {"en": "copper"}, "verdict": "PASS"}
        _normalize_verdict(v)
        self.assertIn("copper", v["suggestion"])
        self.assertIn("{", v["suggestion"])

    def test_non_string_normalized(self):
        v = {"key": "a", "reason": 42, "verdict": "PASS"}
        _normalize_verdict(v)
        self.assertEqual(v["reason"], "42")

    def test_missing_field_set_to_empty(self):
        v: dict = {"key": "a", "verdict": "PASS"}
        _normalize_verdict(v)
        self.assertEqual(v["suggestion"], "")
        self.assertEqual(v["reason"], "")


# ═══════════════════════════════════════════════════════════
# 3.1 TestLlmCallWithRetry
# ═══════════════════════════════════════════════════════════


class TestLlmCallWithRetry(unittest.IsolatedAsyncioTestCase):
    async def test_normal_response_returns_raw_text(self):
        call_count = [0]

        def mock_llm(prompt):
            call_count[0] += 1
            return '[{"key":"a","verdict":"PASS","reason":""}]'

        sem = asyncio.Semaphore(4)
        result = await _llm_call_with_retry(
            "prompt", mock_llm, sem, "TEST", 0, 1, max_retries=3,
        )
        self.assertIn('"key":"a"', result)
        self.assertEqual(call_count[0], 1)

    async def test_truncated_json_retry_then_success(self):
        call_count = [0]

        def mock_llm(prompt):
            call_count[0] += 1
            if call_count[0] == 1:
                return '[{"key":"a"'  # truncated
            return '[{"key":"a","verdict":"PASS","reason":""}]'

        sem = asyncio.Semaphore(4)
        result = await _llm_call_with_retry(
            "prompt", mock_llm, sem, "TEST", 0, 1, max_retries=3,
        )
        self.assertEqual(call_count[0], 2)

    async def test_html_response_raises(self):
        def mock_llm(prompt):
            return "<!DOCTYPE html><html>..."

        sem = asyncio.Semaphore(4)
        with self.assertRaises(RuntimeError):
            await _llm_call_with_retry(
                "prompt", mock_llm, sem, "TEST", 0, 1, max_retries=2,
            )

    async def test_retries_exhausted_raises(self):
        def mock_llm(prompt):
            raise TimeoutError("timeout")

        sem = asyncio.Semaphore(4)
        with self.assertRaises(TimeoutError):
            await _llm_call_with_retry(
                "prompt", mock_llm, sem, "TEST", 0, 1, max_retries=2,
            )

    async def test_semaphore_concurrency_control(self):
        acquired = [0]
        max_concurrent = [0]

        def mock_llm(prompt):
            return '[]'

        sem = asyncio.Semaphore(1)
        await _llm_call_with_retry(
            "prompt", mock_llm, sem, "TEST", 0, 1, max_retries=1,
        )
        self.assertFalse(sem.locked())


# ═══════════════════════════════════════════════════════════
# 3.2 TestBatchProcess
# ═══════════════════════════════════════════════════════════


class TestBatchProcess(unittest.IsolatedAsyncioTestCase):
    async def test_all_batches_summarized(self):
        call_count = [0]

        def mock_llm(prompt):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return '[{"key":"a","verdict":"PASS","reason":""},{"key":"b","verdict":"PASS","reason":""}]'
            if idx == 1:
                return '[{"key":"c","verdict":"PASS","reason":""},{"key":"d","verdict":"PASS","reason":""}]'
            return '[]'

        prompts = ["prompt 0", "prompt 1", "prompt 2"]
        results = await _batch_process(prompts, mock_llm, 2, "TEST", "test_source")
        self.assertEqual(len(results), 4)
        keys = {v["key"] for v in results}
        self.assertEqual(keys, {"a", "b", "c", "d"})
        for v in results:
            self.assertEqual(v["source"], "test_source")

    async def test_error_return_fn_callback(self):
        def mock_llm(prompt):
            if "fail" in prompt:
                raise RuntimeError("failed")
            return '[{"key":"ok","verdict":"PASS","reason":""}]'

        def error_fn(i):
            return [{"key": f"error_{i}", "verdict": "REVIEW", "reason": "error"}]

        prompts = ["batch ok", "batch fail"]
        results = await _batch_process(prompts, mock_llm, 2, "TEST", "src", error_return_fn=error_fn)
        self.assertEqual(len(results), 2)
        keys = {v["key"] for v in results}
        self.assertIn("ok", keys)
        self.assertIn("error_1", keys)

    async def test_no_error_return_fn_skips_failed(self):
        def mock_llm(prompt):
            if "fail" in prompt:
                raise RuntimeError("failed")
            return '[{"key":"ok","verdict":"PASS","reason":""}]'

        prompts = ["batch ok", "batch fail"]
        results = await _batch_process(prompts, mock_llm, 2, "TEST", "src")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], "ok")


# ═══════════════════════════════════════════════════════════
# 4.1 TestReviewBatch
# ═══════════════════════════════════════════════════════════


class TestReviewBatch(unittest.TestCase):
    def test_normal_path_returns_verdicts(self):
        def mock_llm(prompt):
            return '[{"key":"block.copper","verdict":"PASS","reason":""}]'

        bridge = LLMBridge(llm_call=mock_llm)
        entries = [{"key": "block.copper", "en": "Copper", "zh": "\u94dc"}]
        results = bridge.review_batch(entries, batch_size=25)
        self.assertGreaterEqual(len(results), 1)

    def test_no_llm_call_raises(self):
        bridge = LLMBridge()
        with self.assertRaises(RuntimeError):
            bridge.review_batch([])

    def test_multipart_merge_passed_correctly(self):
        def mock_llm(prompt):
            return '[{"key":"book.page.0","verdict":"PASS","reason":""}]'

        bridge = LLMBridge(llm_call=mock_llm)
        entries = [
            {"key": "book.page.0", "en": "Page0", "zh": "\u98750"},
            {"key": "book.page.1", "en": "Page1", "zh": "\u98751"},
        ]
        results = bridge.review_batch(entries, batch_size=25)
        self.assertGreaterEqual(len(results), 1)


# ═══════════════════════════════════════════════════════════
# 4.2 TestReviewUntranslated
# ═══════════════════════════════════════════════════════════


class TestReviewUntranslated(unittest.TestCase):
    def test_normal_path(self):
        def mock_llm(prompt):
            return '[{"key":"test.key","verdict":"PASS","reason":"\u4ee3\u7801\u65e0\u9700\u7ffb\u8bd1"}]'

        bridge = LLMBridge(llm_call=mock_llm)
        entries = [{"key": "test.key", "en": "Hello", "zh": "Hello"}]
        results = bridge.review_untranslated(entries, batch_size=1)
        self.assertGreaterEqual(len(results), 1)

    def test_no_llm_call_raises(self):
        bridge = LLMBridge()
        with self.assertRaises(RuntimeError):
            bridge.review_untranslated([])


# ═══════════════════════════════════════════════════════════
# 4.3 TestFilterVerdicts
# ═══════════════════════════════════════════════════════════


class TestFilterVerdicts(unittest.TestCase):
    def _verdict(self, key, verdict="\u26a0\ufe0f SUGGEST", reason="\u95ee\u9898"):
        return {"key": key, "en_current": "", "zh_current": "", "verdict": verdict, "reason": reason}

    def test_partial_reject(self):
        def mock_llm(prompt):
            return json.dumps([
                {"key": "k1", "verdict": "PASS", "reason": "\u53ef\u4ee5\u63a5\u53d7"},
                {"key": "k2", "verdict": "\u274c FAIL", "reason": "\u786e\u5b9e\u6709\u95ee\u9898"},
                {"key": "k3", "verdict": "PASS", "reason": "\u53ef\u4ee5\u63a5\u53d7"},
                {"key": "k4", "verdict": "\u26a0\ufe0f SUGGEST", "reason": "\u4fdd\u7559\u8b66\u544a"},
                {"key": "k5", "verdict": "\u274c FAIL", "reason": "\u786e\u5b9e\u6709\u95ee\u9898"},
            ])

        bridge = LLMBridge(llm_call=mock_llm)
        verdicts = [self._verdict(f"k{i}") for i in range(1, 6)]
        filtered, discard_records = bridge.filter_verdicts(verdicts, batch_size=5)
        self.assertEqual(len(filtered), 3)
        self.assertEqual(len(discard_records), 2)
        discard_keys = {d["key"] for d in discard_records}
        self.assertIn("k1", discard_keys)
        self.assertIn("k3", discard_keys)

    def test_llm_missed_preserved(self):
        def mock_llm(prompt):
            return json.dumps([
                {"key": "a", "verdict": "PASS", "reason": "\u53ef\u4ee5\u63a5\u53d7"},
                {"key": "b", "verdict": "\u274c FAIL", "reason": "\u786e\u5b9e\u6709\u95ee\u9898"},
            ])

        bridge = LLMBridge(llm_call=mock_llm)
        verdicts = [self._verdict(k) for k in ["a", "b", "c"]]
        filtered, discard_records = bridge.filter_verdicts(verdicts, batch_size=5)
        filtered_keys = {v["key"] for v in filtered}
        self.assertIn("b", filtered_keys)
        self.assertIn("c", filtered_keys)
        self.assertEqual(len(discard_records), 1)

    def test_all_pass_boundary(self):
        def mock_llm(prompt):
            return json.dumps([
                {"key": "x", "verdict": "PASS", "reason": "\u53ef\u4ee5\u63a5\u53d7"},
                {"key": "y", "verdict": "PASS", "reason": "\u53ef\u4ee5\u63a5\u53d7"},
            ])

        bridge = LLMBridge(llm_call=mock_llm)
        verdicts = [self._verdict("x"), self._verdict("y")]
        filtered, discard_records = bridge.filter_verdicts(verdicts, batch_size=5)
        self.assertEqual(len(filtered), 0)
        self.assertEqual(len(discard_records), 2)

    def test_no_llm_call_returns_all(self):
        bridge = LLMBridge()
        verdicts = [self._verdict("x")]
        filtered, discard_records = bridge.filter_verdicts(verdicts)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(len(discard_records), 0)


if __name__ == "__main__":
    unittest.main()
