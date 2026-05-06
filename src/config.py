"""全局配置模块。所有模块从这里取配置，避免重复。

review_config.json 使用嵌套分组结构，
本模块在加载时展平为旧版扁平 API，保持所有消费者兼容。
"""
import json
import sys
from typing import Any

CONFIG_PATH = "review_config.json"

_cfg_cache: dict[str, Any] | None = None

# 顶层分组键
_TOP_GROUPS = {"pipeline", "key_prefixes", "llm", "terminology", "format", "pr", "_comment"}


def _load() -> dict[str, Any]:
    global _cfg_cache
    if _cfg_cache is None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            raw = {}
        _validate(raw)
        _cfg_cache = _flatten(raw)
    return _cfg_cache


def _validate(raw: dict[str, Any]) -> None:
    unknown = set(raw) - _TOP_GROUPS
    if unknown:
        print(
            f"[config] 警告: review_config.json 中有未知顶层分组将被忽略: {', '.join(sorted(unknown))}",
            file=sys.stderr,
        )


def _flatten(raw: dict[str, Any]) -> dict[str, Any]:
    """将嵌套 JSON 展平为旧的扁平键空间。"""
    flat: dict[str, Any] = {}

    # ── pipeline ──
    p = raw.get("pipeline", {})
    flat["max_workers"] = p.get("max_workers", 4)
    flat["filter_batch_size"] = p.get("filter_batch_size", 50)

    # ── key_prefixes ──
    # 旧格式: dict[str, list[str]] → 新格式: dict[str, dict]
    # llm_required_prefixes 从嵌入的 llm_required 标记自动派生
    kp = raw.get("key_prefixes", {})
    flat["key_prefix_prompts"] = kp
    flat["llm_required_prefixes"] = [
        prefix for prefix, info in kp.items() if info.get("llm_required")
    ]

    # ── llm ──
    l = raw.get("llm", {})
    flat["review_system_prompt"] = l.get("system_prompt")
    flat["review_header_prefix"] = l.get("header_prefix")
    flat["default_review_focus"] = l.get("default_review_focus")
    flat["review_instruction"] = l.get("review_instruction", [])
    flat["review_principles"] = l.get("review_principles", [])
    flat["merge_system_prompt"] = l.get("merge_system_prompt", [])
    flat["keyboard_guidance"] = l.get("keyboard_guidance")
    flat["mouse_guidance"] = l.get("mouse_guidance")

    filt = l.get("filter", {})
    flat["filter_system_prompt"] = filt.get("system_prompt")
    flat["filter_instruction"] = filt.get("instruction", [])

    # ── terminology ──
    t = raw.get("terminology", {})
    flat["term_min_freq"] = t.get("min_freq", 5)
    flat["term_min_consensus"] = t.get("min_consensus", 0.6)
    flat["term_max_zh_len"] = t.get("max_zh_len", 40)
    flat["term_max_en_len"] = t.get("max_en_len", 60)
    flat["term_consensus_min_total"] = t.get("consensus_min_total", 3)
    flat["fuzzy_cluster_threshold"] = t.get("fuzzy_cluster_threshold", 65.0)
    flat["fuzzy_cluster_top_n"] = t.get("fuzzy_cluster_top_n", 200)
    flat["term_blacklist"] = t.get("blacklist", [])

    # ── format ──
    fmt = raw.get("format", {})
    flat["desc_key_suffixes"] = fmt.get("desc_key_suffixes", [])
    flat["punctuation_spacing_whitelist"] = fmt.get("punctuation_spacing_whitelist", [])

    # ── pr ──
    pr = raw.get("pr", {})
    flat["pr_change_context_prompt"] = pr.get("change_context_prompt")
    flat["default_pr_repo"] = pr.get("default_repo", "CFPAOrg/Minecraft-Mod-Language-Package")

    return flat


def get(key: str, default: Any = None) -> Any:
    val = _load().get(key, default)
    if val is None and default is None:
        raise KeyError(f"review_config.json 缺少必填键: {key}")
    return val


# ═══════════════════════════════════════════════════════════
# 常用配置项（保持与旧版完全相同的 API）
# ═══════════════════════════════════════════════════════════

DESC_KEY_SUFFIXES: tuple[str, ...] = tuple(
    get("desc_key_suffixes", [".desc", ".description", ".lore", ".tooltip",
                               ".flavor", ".info", ".message", ".text"])
)

PUNCTUATION_SPACING_WHITELIST: tuple[str, ...] = tuple(
    get("punctuation_spacing_whitelist", ["book.", "patchouli."])
)

TERM_MIN_FREQ: int = get("term_min_freq", 5)
TERM_MIN_CONSENSUS: float = get("term_min_consensus", 0.6)
TERM_MAX_ZH_LEN: int = get("term_max_zh_len", 40)
TERM_MAX_EN_LEN: int = get("term_max_en_len", 60)
TERM_CONSENSUS_MIN_TOTAL: int = get("term_consensus_min_total", 3)
FUZZY_CLUSTER_THRESHOLD: float = get("fuzzy_cluster_threshold", 65.0)
FUZZY_CLUSTER_TOP_N: int = get("fuzzy_cluster_top_n", 200)
MAX_WORKERS: int = get("max_workers", 4)

KEY_PREFIX_PROMPTS: dict[str, dict[str, Any]] = get("key_prefix_prompts")
LLM_REQUIRED_PREFIXES: set[str] = set(get("llm_required_prefixes"))


def _as_text(val: str | list[str]) -> str:
    return "\n".join(val) if isinstance(val, list) else val


DEFAULT_REVIEW_FOCUS: str = get("default_review_focus")
REVIEW_SYSTEM_PROMPT: str = get("review_system_prompt")
REVIEW_INSTRUCTION: str = _as_text(get("review_instruction"))
REVIEW_PRINCIPLES: str = _as_text(get("review_principles"))
MERGE_SYSTEM_PROMPT: str = _as_text(get("merge_system_prompt"))
REVIEW_HEADER_PREFIX: str = get("review_header_prefix")
KEYBOARD_GUIDANCE: str = get("keyboard_guidance")
MOUSE_GUIDANCE: str = get("mouse_guidance")

FILTER_SYSTEM_PROMPT: str = get("filter_system_prompt")
FILTER_INSTRUCTION: str = _as_text(get("filter_instruction"))
FILTER_BATCH_SIZE: int = get("filter_batch_size", 50)

DEFAULT_PR_REPO: str = get("default_pr_repo", "CFPAOrg/Minecraft-Mod-Language-Package")
