"""LLM 客户端工厂 —— OpenAI 兼容 API 调用、日志、重试逻辑。

日志中的 [id=xxxxxxx] 是每次调用的唯一识别码，用于在异步并发日志中
对齐 request (Prompt) 和 response (Response)。
"""
import datetime
import time
import uuid
from pathlib import Path
from typing import Callable

from src.logging import info, warn

from src.models import LLMCallable
from src import config as _cfg


def create_openai_llm_call(
    api_key: str,
    model: str = "gpt-4o",
    base_url: str = "https://api.openai.com/v1",
    *,
    system_prompt: str | None = None,
    log_dir: str = "logs",
    reasoning_effort: str | None = None,
    label: str = "LLM",
) -> LLMCallable:
    if system_prompt is None:
        system_prompt = _cfg.REVIEW_SYSTEM_PROMPT

    # OpenAI SDK 会自动追加 /chat/completions，不要让它重复
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请安装 openai: pip install openai")

    client = OpenAI(api_key=api_key, base_url=base_url)
    call_count = [0]  # Mutable list in closure — intentional design

    # token 用量统计
    usage = {  # Mutable dict in closure — intentional design
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "calls": 0,
    }

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)
    latest_path = log_dir_path / "latest.log"

    # 仅轮转有内容的日志（多 label 共用同一 log_dir 时避免空文件轮转）
    if latest_path.exists() and latest_path.stat().st_size > 0:
        mtime = latest_path.stat().st_mtime
        archive_name = time.strftime("%Y%m%d-%H%M%S", time.localtime(mtime))
        latest_path.rename(log_dir_path / f"latest.{archive_name}.log")

    def _log(level: str, msg: str) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(latest_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")

    MAX_RETRIES = _cfg.get("llm_max_retries", 5)
    _temperature = _cfg.get("llm_temperature", 0.1)
    _max_tokens = _cfg.get("llm_max_tokens", 32768)

    def call(prompt: str) -> str:
        call_count[0] += 1
        n = call_count[0]
        call_id = uuid.uuid4().hex[:8]
        tag = f"[{label}#{n}] [id={call_id}]"
        _log("INFO", f"{tag} === Call #{n} ({len(prompt)} chars, ~{len(prompt)//4} tokens) ===")
        _log("INFO", f"{tag} Prompt:\n{prompt}")

        retries = 0
        while True:
            try:
                kwargs: dict = dict(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=_temperature,
                    max_tokens=_max_tokens,
                )
                if reasoning_effort:
                    kwargs["extra_body"] = {"reasoning_effort": reasoning_effort}
                resp = client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content or ""
                _log("INFO", f"{tag} Response:\n{content}")
                if resp.usage:
                    usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
                    usage["completion_tokens"] += resp.usage.completion_tokens or 0
                    usage["total_tokens"] += resp.usage.total_tokens or 0
                    usage["calls"] += 1
                return content
            except Exception as e:
                err_str = str(e)
                err_lower = err_str.lower()
                retryable = (
                    "429" in err_str or "rate" in err_lower
                    or "connection" in err_lower or "timeout" in err_lower
                    or "reset" in err_lower or "refused" in err_lower
                    or "remote disconnect" in err_lower or "eof" in err_lower
                    or "server disconnected" in err_lower
                    or "500" in err_str or "502" in err_str
                    or "503" in err_str or "504" in err_str
                )
                if retryable and retries < MAX_RETRIES:
                    delay = min(5 * (1 << retries), 60)
                    retries += 1
                    _log("WARN", f"{tag} 可重试错误, {delay}s 后重试 (第{retries}/{MAX_RETRIES}次): {err_str[:200]}")
                    warn(f"  {tag} {delay}s 后重试 (第{retries}/{MAX_RETRIES}次): {err_str[:120]}")
                    time.sleep(delay)
                else:
                    if retries >= MAX_RETRIES:
                        _log("ERROR", f"{tag} 已达最大重试次数({MAX_RETRIES}): {err_str[:200]}")
                    raise

    call.usage = usage  # type: ignore[attr-defined]
    return call


def create_dry_run_llm_call() -> LLMCallable:
    def call(prompt: str) -> str:
        info(f"[DRY RUN] Prompt length: {len(prompt)} chars")
        return "[]"
    return call
