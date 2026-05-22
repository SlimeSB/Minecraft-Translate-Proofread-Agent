"""全局配置模块。所有模块从这里取配置，避免重复。

review_config.json 使用嵌套分组结构，
本模块在加载时展平为旧版扁平 API，保持所有消费者兼容。
"""
import json
import re
import sys
from typing import Any

CONFIG_PATH = "review_config.json"

# Module-level cache — loaded once at startup, never mutated at runtime
_cfg_cache: dict[str, Any] | None = None

# 顶层分组键
_TOP_GROUPS = {"pipeline", "manual_formats", "llm", "terminology", "format", "pr", "_comment"}

_PROMPT_WHITELIST: set[str] = {
    "review_full_header", "filter_header", "filter_entry_block",
    "filter_entry_suggestion", "untranslated_prompt",
    "reference_section", "glossary_section", "fuzzy_section",
    "dict_section", "cross_version_ref_block", "auto_check_line",
    "entry_key_line", "entry_en_line", "entry_old_en_line",
    "entry_old_zh_line", "entry_ref_en_line", "entry_ref_zh_line",
    "entry_en_context_label", "entry_zh_context_label",
    "entry_en_label", "entry_zh_label",
    "glossary_term_line", "fuzzy_match_line",
    "header_with_refs", "filter_entry_block_with_suggestion",
    "filter_prompt_assembly", "untranslated_entry_block",
    "external_dict_heading", "vanilla_terms_heading",
    "minecraft_dict_heading", "minecraft_dict_fuzzy_label", "block_separator",
    "term_verification_prompt", "term_verification_term_line",
    "term_verification_context_line",
    "external_dict_output", "minecraft_dict_header",
    "minecraft_dict_sensitive_warning", "minecraft_dict_output",
}

# 语言文件元数据键前缀正则 — 加载 JSON 时过滤 _comment* 键
COMMENT_KEY_PATTERN = r"^_comment"


def _load() -> dict[str, Any]:
    global _cfg_cache
    if _cfg_cache is None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"[config] 配置加载失败: {e}", file=sys.stderr)
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
    flat["review_batch_size"] = p.get("review_batch_size", 25)
    flat["fts_recall_multiplier"] = p.get("fts_recall_multiplier", 10)
    flat["fts_recall_min"] = p.get("fts_recall_min", 50)
    flat["fuzzy_trigger_patterns"] = p.get("fuzzy_trigger_patterns", [".desc", "death.attack.", "advancements."])
    flat["format_specifier_pattern"] = p.get("format_specifier_pattern", "^%[a-zA-Z0-9_.$]+$")
    flat["word_extract_pattern"] = p.get("word_extract_pattern", "[A-Za-z]+")
    vd = p.get("vanilla_dict", {})
    flat["vd_per_word_triggers"] = vd.get("per_word_trigger_words", ["block", "blocks", "item", "items"])
    flat["vd_fuzzy_triggers"] = vd.get("fuzzy_trigger_words", ["desc"])
    flat["vd_word_count_threshold"] = vd.get("word_count_threshold", 6)
    flat["vd_similarity_threshold"] = vd.get("vd_similarity_threshold", 60.0)
    flat["default_namespace_label"] = p.get("default_namespace_label", "其他")
    flat["singleton_length_threshold"] = p.get("singleton_length_threshold", 2000)

    # ── manual_formats ──
    mf = raw.get("manual_formats", {})
    flat["manual_formats"] = mf

    # ── llm ──
    l = raw.get("llm", {})
    flat["llm_max_retries"] = l.get("max_retries", 5)
    flat["llm_temperature"] = l.get("temperature", 0.1)
    flat["llm_max_tokens"] = l.get("max_tokens", 32768)
    flat["llm_review_retries"] = l.get("review_retries", 2)
    flat["review_system_prompt"] = l.get("system_prompt")
    flat["review_header_prefix"] = l.get("header_prefix")
    flat["default_review_focus"] = l.get("default_review_focus")
    flat["review_instruction"] = l.get("review_instruction", [])
    flat["review_principles"] = l.get("review_principles", [])
    flat["dict_store_headers_to_strip"] = l.get("dict_store_headers_to_strip", [])

    filt = l.get("filter", {})
    flat["filter_system_prompt"] = filt.get("system_prompt")
    flat["filter_instruction"] = filt.get("instruction", [])

    # ── prompt_templates ──
    pt = l.get("prompt_templates", {})
    for key in _PROMPT_WHITELIST:
        flat[f"prompt_{key}"] = pt.get(key, [])

    _unreferenced = set(pt) - _PROMPT_WHITELIST
    if _unreferenced:
        print(
            f"[config] 警告: review_config.json 的 prompt_templates 中有未识别的 key，将被丢弃: "
            f"{', '.join(sorted(_unreferenced))}",
            file=sys.stderr,
        )

    # ── terminology ──
    t = raw.get("terminology", {})
    flat["term_min_freq"] = t.get("min_freq", 5)
    flat["term_min_consensus"] = t.get("min_consensus", 0.6)
    flat["term_max_zh_len"] = t.get("max_zh_len", 40)
    flat["term_max_en_len"] = t.get("max_en_len", 60)
    flat["term_consensus_min_total"] = t.get("consensus_min_total", 3)
    flat["term_blacklist"] = t.get("blacklist", [])
    flat["max_keys_per_term"] = t.get("max_keys_per_term", 20)
    flat["max_keys_raw"] = t.get("max_keys_raw", 5)
    flat["term_max_ngram"] = t.get("max_ngram", 3)

    # ── format ──
    fmt = raw.get("format", {})
    flat["desc_key_suffixes"] = fmt.get("desc_key_suffixes", [])
    flat["punctuation_spacing_whitelist"] = fmt.get("punctuation_spacing_whitelist", [])
    flat["en_preview_len"] = fmt.get("en_preview_len", 60)

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

# Computed at import time; config doesn't change at runtime so this is fine
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
TERM_MAX_NGRAM: int = get("term_max_ngram", 3)
MAX_WORKERS: int = get("max_workers", 4)

MANUAL_FORMATS: dict[str, dict[str, Any]] = get("manual_formats")
SINGLETON_LENGTH_THRESHOLD: int = get("singleton_length_threshold")

# 无名空间哨兵 — 键分类和报告生成中共用
DEFAULT_NAMESPACE = "__default__"
DEFAULT_NAMESPACE_LABEL: str = get("default_namespace_label", "其他")

# 带序号键匹配，如 tooltip[0]、advancements.story.root.1
# 用于检测多段条目的分段索引
RE_INDEXED_KEY: re.Pattern = re.compile(r"^(.*?)(?:\.|\[)(\d+)\]?$")

# printf 风格格式占位符匹配，用于过滤 %d, %s, %1$s, %.2f 等无意义搜索词
RE_FORMAT_SPECIFIER: re.Pattern = re.compile(get("format_specifier_pattern"))

# 无锚点版本，用于从文本中剥离格式占位符（在单词提取前处理）
_FORMAT_STRIP_RAW = get("format_specifier_pattern")
_FORMAT_STRIP_RAW = _FORMAT_STRIP_RAW.removeprefix("^").removesuffix("$") if _FORMAT_STRIP_RAW else r"%[a-zA-Z0-9_.$]+"
RE_FORMAT_SPECIFIER_STRIP: re.Pattern = re.compile(_FORMAT_STRIP_RAW)

# 单词提取正则 — 用于词典查询时从文本中提取候选词
WORD_EXTRACT_PATTERN: re.Pattern = re.compile(get("word_extract_pattern"))

# vanilla_dict 搜索策略配置
VD_PER_WORD_TRIGGERS: set[str] = set(get("vd_per_word_triggers"))
VD_FUZZY_TRIGGERS: set[str] = set(get("vd_fuzzy_triggers"))
VD_WORD_COUNT_THRESHOLD: int = get("vd_word_count_threshold")


def _as_text(val: str | list[str]) -> str:
    return "\n".join(val) if isinstance(val, list) else val


DEFAULT_REVIEW_FOCUS: str = get("default_review_focus")
REVIEW_SYSTEM_PROMPT: str = get("review_system_prompt")
REVIEW_INSTRUCTION: str = _as_text(get("review_instruction"))
REVIEW_PRINCIPLES: str = _as_text(get("review_principles"))
REVIEW_HEADER_PREFIX: str = get("review_header_prefix")

FILTER_SYSTEM_PROMPT: str = get("filter_system_prompt")
FILTER_INSTRUCTION: str = _as_text(get("filter_instruction"))
FILTER_BATCH_SIZE: int = get("filter_batch_size", 50)

# prompt 模板
PROMPT_REVIEW_FULL_HEADER: str = _as_text(get("prompt_review_full_header"))
PROMPT_REFERENCE_SECTION: str = get("prompt_reference_section", "")
PROMPT_GLOSSARY_SECTION: str = get("prompt_glossary_section", "")
PROMPT_FUZZY_SECTION: str = get("prompt_fuzzy_section", "")
PROMPT_DICT_SECTION: str = get("prompt_dict_section", "")
PROMPT_CROSS_VERSION_REF_BLOCK: str = _as_text(get("prompt_cross_version_ref_block"))
PROMPT_AUTO_CHECK_LINE: str = get("prompt_auto_check_line", "")
PROMPT_ENTRY_KEY_LINE: str = get("prompt_entry_key_line", "")
PROMPT_ENTRY_EN_LINE: str = get("prompt_entry_en_line", "")
PROMPT_ENTRY_OLD_EN_LINE: str = get("prompt_entry_old_en_line", "")
PROMPT_ENTRY_OLD_ZH_LINE: str = get("prompt_entry_old_zh_line", "")
PROMPT_ENTRY_REF_EN_LINE: str = get("prompt_entry_ref_en_line", "")
PROMPT_ENTRY_REF_ZH_LINE: str = get("prompt_entry_ref_zh_line", "")
ENTRY_EN_CONTEXT_LABEL: str = get("prompt_entry_en_context_label", "")
ENTRY_ZH_CONTEXT_LABEL: str = get("prompt_entry_zh_context_label", "")
ENTRY_EN_LABEL: str = get("prompt_entry_en_label", "")
ENTRY_ZH_LABEL: str = get("prompt_entry_zh_label", "")
PROMPT_GLOSSARY_TERM_LINE: str = get("prompt_glossary_term_line", "")
PROMPT_FUZZY_MATCH_LINE: str = get("prompt_fuzzy_match_line", "")
PROMPT_HEADER_WITH_REFS: str = get("prompt_header_with_refs", "")
PROMPT_FILTER_BLOCK_WITH_SUGGESTION: str = get("prompt_filter_entry_block_with_suggestion", "")
PROMPT_FILTER_ASSEMBLY: str = get("prompt_filter_prompt_assembly", "")
PROMPT_UNTRANSLATED_ENTRY_BLOCK: str = get("prompt_untranslated_entry_block", "")
EXTERNAL_DICT_HEADING: str = get("prompt_external_dict_heading", "")
VANILLA_TERMS_HEADING: str = get("prompt_vanilla_terms_heading", "")
MINECRAFT_DICT_HEADING: str = get("prompt_minecraft_dict_heading", "")
MINECRAFT_DICT_FUZZY_LABEL: str = get("prompt_minecraft_dict_fuzzy_label", "模糊匹配：")
PROMPT_BLOCK_SEPARATOR: str = get("prompt_block_separator", "\n\n")
PROMPT_TERM_VERIFICATION: str = _as_text(get("prompt_term_verification_prompt"))
PROMPT_TERM_VERIFY_TERM_LINE: str = get("prompt_term_verification_term_line", "")
PROMPT_TERM_VERIFY_CTX_LINE: str = get("prompt_term_verification_context_line", "")
PROMPT_EXTERNAL_DICT_OUTPUT: str = get("prompt_external_dict_output", "")
PROMPT_FILTER_HEADER: str = _as_text(get("prompt_filter_header"))
PROMPT_FILTER_ENTRY_BLOCK: str = _as_text(get("prompt_filter_entry_block"))
PROMPT_FILTER_ENTRY_SUGGESTION: str = get("prompt_filter_entry_suggestion", "")
PROMPT_UNTRANSLATED: str = _as_text(get("prompt_untranslated_prompt"))

MINECRAFT_DICT_HEADER: str = get("prompt_minecraft_dict_header", "原版词典：")
MINECRAFT_DICT_SENSITIVE_WARNING: str = get("prompt_minecraft_dict_sensitive_warning", "")
PROMPT_MINECRAFT_DICT_OUTPUT: str = get("prompt_minecraft_dict_output", "")
DICT_STORE_HEADERS_TO_STRIP: tuple[str, ...] = tuple(get("dict_store_headers_to_strip", []))

DEFAULT_PR_REPO: str = get("default_pr_repo", "CFPAOrg/Minecraft-Mod-Language-Package")
