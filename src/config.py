"""全局配置模块。所有模块从这里取配置，避免重复。"""
import json
from typing import Any

CONFIG_PATH = "review_config.json"

_cfg_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cfg_cache
    if _cfg_cache is None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _cfg_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _cfg_cache = {}
    return _cfg_cache


def get(key: str, default: Any = None) -> Any:
    return _load().get(key, default)


# ── 常用配置项 ──

DESC_KEY_SUFFIXES: tuple[str, ...] = tuple(
    get("desc_key_suffixes", [".desc", ".description", ".lore", ".tooltip",
                               ".flavor", ".info", ".message", ".text"])
)

TERM_MIN_FREQ = get("term_min_freq", 5)
TERM_MIN_CONSENSUS = get("term_min_consensus", 0.6)
TERM_MAX_ZH_LEN = get("term_max_zh_len", 40)
TERM_MAX_EN_LEN = get("term_max_en_len", 60)
TERM_CONSENSUS_MIN_TOTAL = get("term_consensus_min_total", 3)
FUZZY_CLUSTER_THRESHOLD = get("fuzzy_cluster_threshold", 65.0)
FUZZY_CLUSTER_TOP_N = get("fuzzy_cluster_top_n", 200)

# key 前缀 → [类别标签, 审查重点]
KEY_PREFIX_PROMPTS: dict[str, list[str]] = get("key_prefix_prompts", {})

# LLM 审校必选前缀
LLM_REQUIRED_PREFIXES: set[str] = set(get("llm_required_prefixes", []))

# 默认审查重点（未匹配前缀时使用）
DEFAULT_REVIEW_FOCUS = get("default_review_focus", "翻译需准确自然; 术语一致; 匹配语境")

# 风格参考文本
STYLE_REFERENCE = get("style_reference", "")

# 审校 system prompt
REVIEW_SYSTEM_PROMPT = get("review_system_prompt", "你是一位翻译审校专家。请按要求输出JSON。")

# 审校指令
REVIEW_INSTRUCTION = get("review_instruction", '对每条输出: {"key": "...", "verdict": "...", "suggestion": "...", "reason": "..."}')
REVIEW_PRINCIPLES = get("review_principles", "")
