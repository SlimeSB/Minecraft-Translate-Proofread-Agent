"""全局配置模块。所有模块从这里取配置，避免重复。"""
import json
import sys
from typing import Any

CONFIG_PATH = "review_config.json"

_cfg_cache: dict[str, Any] | None = None

# 已知合法配置键，其余键启动时发出警告
_KNOWN_KEYS: set[str] = {
    "_note",
    "desc_key_suffixes",
    "key_prefix_prompts",
    "llm_required_prefixes",
    "default_review_focus",
    "style_reference",
    "review_system_prompt",
    "review_instruction",
    "review_principles",
    "merge_system_prompt",
    "review_header_prefix",
    "keyboard_guidance",
    "mouse_guidance",
    "term_min_freq",
    "term_min_consensus",
    "term_max_zh_len",
    "term_max_en_len",
    "term_consensus_min_total",
    "fuzzy_cluster_threshold",
    "fuzzy_cluster_top_n",
    "term_blacklist",
    "max_workers",
}


def _load() -> dict[str, Any]:
    global _cfg_cache
    if _cfg_cache is None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _cfg_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _cfg_cache = {}
        _validate(_cfg_cache)
    return _cfg_cache


def _validate(cfg: dict[str, Any]) -> None:
    unknown = set(cfg) - _KNOWN_KEYS
    if unknown:
        print(
            f"[config] 警告: review_config.json 中有未知键将被忽略: {', '.join(sorted(unknown))}",
            file=sys.stderr,
        )


def get(key: str, default: Any = None) -> Any:
    val = _load().get(key, default)
    if val is None and default is None:
        raise KeyError(f"review_config.json 缺少必填键: {key}")
    return val


# ── 常用配置项 ──

DESC_KEY_SUFFIXES: tuple[str, ...] = tuple(
    get("desc_key_suffixes", [".desc", ".description", ".lore", ".tooltip",
                               ".flavor", ".info", ".message", ".text"])
)

TERM_MIN_FREQ: int = get("term_min_freq", 5)
TERM_MIN_CONSENSUS: float = get("term_min_consensus", 0.6)
TERM_MAX_ZH_LEN: int = get("term_max_zh_len", 40)
TERM_MAX_EN_LEN: int = get("term_max_en_len", 60)
TERM_CONSENSUS_MIN_TOTAL: int = get("term_consensus_min_total", 3)
FUZZY_CLUSTER_THRESHOLD: float = get("fuzzy_cluster_threshold", 65.0)
FUZZY_CLUSTER_TOP_N: int = get("fuzzy_cluster_top_n", 200)
MAX_WORKERS: int = get("max_workers", 4)

KEY_PREFIX_PROMPTS: dict[str, list[str]] = get("key_prefix_prompts")
LLM_REQUIRED_PREFIXES: set[str] = set(get("llm_required_prefixes"))

# ── Prompt / 引导文本（必填，缺失则报错）───

DEFAULT_REVIEW_FOCUS: str = get("default_review_focus")
STYLE_REFERENCE: str = get("style_reference")
REVIEW_SYSTEM_PROMPT: str = get("review_system_prompt")
REVIEW_INSTRUCTION: str = get("review_instruction")
REVIEW_PRINCIPLES: str = get("review_principles")
MERGE_SYSTEM_PROMPT: str = get("merge_system_prompt")
REVIEW_HEADER_PREFIX: str = get("review_header_prefix")
KEYBOARD_GUIDANCE: str = get("keyboard_guidance")
MOUSE_GUIDANCE: str = get("mouse_guidance")
