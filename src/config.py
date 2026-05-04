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
    "filter_system_prompt",
    "filter_instruction",
    "filter_batch_size",
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

# 需要 LLM 审校的描述性 key 后缀（如 .desc / .tooltip）
DESC_KEY_SUFFIXES: tuple[str, ...] = tuple(
    get("desc_key_suffixes", [".desc", ".description", ".lore", ".tooltip",
                               ".flavor", ".info", ".message", ".text"])
)

# 术语提取：最低频次（低于此值的 n-gram 不进入术语表）
TERM_MIN_FREQ: int = get("term_min_freq", 5)
# 术语提取：中文共识比例（同一英文对应多种中文时，需 ≥ 此比例才收录）
TERM_MIN_CONSENSUS: float = get("term_min_consensus", 0.6)
# 术语提取：中文最大长度（超过此长度不收录）
TERM_MAX_ZH_LEN: int = get("term_max_zh_len", 40)
# 术语提取：英文最大长度
TERM_MAX_EN_LEN: int = get("term_max_en_len", 60)
# 术语提取：共识计算的最低样本数
TERM_CONSENSUS_MIN_TOTAL: int = get("term_consensus_min_total", 3)
# 词形模糊聚类相似度阈值（0-100）
FUZZY_CLUSTER_THRESHOLD: float = get("fuzzy_cluster_threshold", 65.0)
# 词形模糊聚类最多参与条目数
FUZZY_CLUSTER_TOP_N: int = get("fuzzy_cluster_top_n", 200)
# 异步 LLM 最大并发数
MAX_WORKERS: int = get("max_workers", 4)

# key 前缀 → [类别标签, 审查重点] 映射
KEY_PREFIX_PROMPTS: dict[str, list[str]] = get("key_prefix_prompts")
# 强制 LLM 审校的 key 前缀（不可自动通过）
LLM_REQUIRED_PREFIXES: set[str] = set(get("llm_required_prefixes"))

# ── Prompt / 引导文本（必填，缺失则报错）───

# 未匹配前缀的默认审查重点
DEFAULT_REVIEW_FOCUS: str = get("default_review_focus")
# 风格参考（注入到每条 prompt）
STYLE_REFERENCE: str = get("style_reference")
# LLM system prompt
REVIEW_SYSTEM_PROMPT: str = get("review_system_prompt")
# LLM 输出格式指令
REVIEW_INSTRUCTION: str = get("review_instruction")
# 审校普适原则（注入到每条 prompt）
REVIEW_PRINCIPLES: str = get("review_principles")
# 术语归并 LLM system prompt
MERGE_SYSTEM_PROMPT: str = get("merge_system_prompt")
# prompt 标题前缀
REVIEW_HEADER_PREFIX: str = get("review_header_prefix")
# 检测到键盘按键时的补充指南
KEYBOARD_GUIDANCE: str = get("keyboard_guidance")
# 检测到鼠标操作时的补充指南
MOUSE_GUIDANCE: str = get("mouse_guidance")

# ── Phase 5: 最终 LLM 过滤 ──

FILTER_SYSTEM_PROMPT: str = get("filter_system_prompt")
FILTER_INSTRUCTION: str = get("filter_instruction")
FILTER_BATCH_SIZE: int = get("filter_batch_size", 50)
