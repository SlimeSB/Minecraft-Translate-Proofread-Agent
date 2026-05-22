"""LLM 模块 —— 向后兼容 re-export。"""
from src.llm.client import create_dry_run_llm_call, create_openai_llm_call, LLMCallable
from src.llm.bridge import LLMBridge, interactive_entry_review, parse_review_response
from src.llm.prompts import (
    build_entry_block,
    build_filter_prompt,
    build_review_prompt,
    detect_input_guidance,
    filter_for_llm,
    is_manual_format,
    manual_format_label,
    merge_multipart_entries,
    needs_llm_review,
    should_singleton,
)

__all__ = [
    # client
    "create_openai_llm_call",
    "create_dry_run_llm_call",
    "LLMCallable",
    # bridge
    "LLMBridge",
    "parse_review_response",
    "interactive_entry_review",
    # prompts
    "detect_input_guidance",
    "filter_for_llm",
    "needs_llm_review",
    "is_manual_format",
    "manual_format_label",
    "should_singleton",
    "build_entry_block",
    "build_review_prompt",
    "build_filter_prompt",
    "merge_multipart_entries",
]
