"""向后兼容重导出 —— 请改用 src.llm.* 各子模块。"""
from src.llm.client import create_dry_run_llm_call, create_openai_llm_call, LLMCallable
from src.llm.bridge import LLMBridge, interactive_entry_review, parse_review_response
from src.llm.prompts import (
    build_entry_block,
    build_filter_prompt,
    build_review_prompt,
    classify_entries,
    classify_key,
    detect_input_guidance as _detect_input_guidance,
    filter_for_llm,
    merge_multipart_entries,
    needs_llm_review,
)

__all__ = [
    "create_openai_llm_call",
    "create_dry_run_llm_call",
    "LLMCallable",
    "LLMBridge",
    "parse_review_response",
    "interactive_entry_review",
    "classify_entries",
    "classify_key",
    "filter_for_llm",
    "needs_llm_review",
    "build_entry_block",
    "build_review_prompt",
    "build_filter_prompt",
    "merge_multipart_entries",
]
