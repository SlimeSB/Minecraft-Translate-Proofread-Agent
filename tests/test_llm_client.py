"""测试 src/llm/client.py —— 干运行模式、指数退避重试逻辑。"""
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.llm.client import create_dry_run_llm_call, create_openai_llm_call


# ═══════════════════════════════════════════════════════════
# 5.1 TestCreateDryRunCall
# ═══════════════════════════════════════════════════════════


class TestCreateDryRunCall(unittest.TestCase):
    def test_returns_empty_array(self):
        call = create_dry_run_llm_call()
        result = call("any prompt")
        self.assertEqual(result, "[]")

    def test_logs_prompt_length(self):
        call = create_dry_run_llm_call()
        prompt = "x" * 100
        result = call(prompt)
        self.assertEqual(result, "[]")

    def test_no_network_request(self):
        call = create_dry_run_llm_call()
        result = call("hello world")
        self.assertEqual(result, "[]")


# ═══════════════════════════════════════════════════════════
# 5.2 TestOpenaiRetryLogic
# ═══════════════════════════════════════════════════════════


class TestOpenaiRetryLogic(unittest.TestCase):
    def setUp(self):
        self.sleep_patcher = patch("time.sleep")
        self.mock_sleep = self.sleep_patcher.start()

        self.openai_patcher = patch("openai.OpenAI")
        self.mock_openai_cls = self.openai_patcher.start()
        self.mock_client = MagicMock()
        self.mock_openai_cls.return_value = self.mock_client

        self.temp_log_dir = tempfile.mkdtemp()

    def tearDown(self):
        self.openai_patcher.stop()
        self.sleep_patcher.stop()
        shutil.rmtree(self.temp_log_dir, ignore_errors=True)

    def _create_call(self, **kwargs):
        kwargs.setdefault("api_key", "sk-test-key")
        kwargs.setdefault("model", "gpt-4o")
        kwargs.setdefault("base_url", "https://api.openai.com/v1")
        kwargs.setdefault("log_dir", self.temp_log_dir)
        return create_openai_llm_call(**kwargs)

    @staticmethod
    def _mock_response(content):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        resp.usage = None
        return resp

    def test_429_retry_then_success(self):
        error_429 = Exception("429 Too Many Requests")
        success = self._mock_response("[]")
        self.mock_client.chat.completions.create.side_effect = [error_429, error_429, success]

        call = self._create_call()
        call("test prompt")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 3)

    def test_500_retry_exhausted(self):
        error_500 = Exception("500 Internal Server Error")
        self.mock_client.chat.completions.create.side_effect = [error_500] * 10

        call = self._create_call()
        with self.assertRaises(Exception):
            call("test prompt")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 6)

    def test_400_no_retry(self):
        error_400 = Exception("400 Bad Request")
        self.mock_client.chat.completions.create.side_effect = error_400

        call = self._create_call()
        with self.assertRaises(Exception):
            call("test prompt")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 1)

    def test_connection_error_triggers_retry(self):
        error_conn = Exception("Connection refused")
        success = self._mock_response("[]")
        self.mock_client.chat.completions.create.side_effect = [error_conn, success]

        call = self._create_call()
        call("test prompt")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 2)

    def test_normal_response_no_retry(self):
        self.mock_client.chat.completions.create.return_value = self._mock_response("[]")

        call = self._create_call()
        result = call("test prompt")
        self.assertEqual(result, "[]")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 1)

    def test_reasoning_effort_passed(self):
        self.mock_client.chat.completions.create.return_value = self._mock_response("[]")

        call = self._create_call(reasoning_effort="medium")
        call("test prompt")

        kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        self.assertIn("extra_body", kwargs)
        self.assertEqual(kwargs["extra_body"]["reasoning_effort"], "medium")


if __name__ == "__main__":
    unittest.main()
