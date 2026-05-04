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

# 术语归并 prompt
MERGE_SYSTEM_PROMPT = get("merge_system_prompt", "你是英文术语规范化专家。请判断是否合并。只输出JSON数组。")

# 审校 header 前缀
REVIEW_HEADER_PREFIX = get("review_header_prefix", "你是Minecraft模组简中翻译审校专家")

# 输入设备翻译专项指南（键盘/鼠标，用于 LLM prompt 动态补充）
KEYBOARD_GUIDANCE = get("keyboard_guidance", "检测到预设的键盘按键，建议保留原文。")
MOUSE_GUIDANCE = get("mouse_guidance", "检测到鼠标操作，注意使用"左键点击"、"右击"、"按住右键"等，而非"左键"、"右键"")

# LLM 并行批次数
MAX_WORKERS = get("max_workers", 4)
