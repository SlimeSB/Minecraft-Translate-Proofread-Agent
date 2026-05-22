"""LLM 提示词构建器。

包含：条目分类、审校提示词、Phase 5 过滤提示词、术语覆盖率检查。
"""
import re

from src import config as cfg
from src.config import DEFAULT_NAMESPACE
from src.dictionary.external import ExternalDictStore
from src.dictionary.vanilla_terms import VanillaTermsStore
from src.dictionary.protocol import collect_hints
from src.tools.key_alignment import iter_indexed_groups
from src.models import (
    AutoVerdictsMap,
    EntryDict,
    FuzzyResultDict,
    FuzzyResultsMap,
    GlossaryDict,
    GroupedEntries,
    KeyPrefixConfig,
    MultipartContext,
    VerdictDict,
)

# ═══════════════════════════════════════════════════════════
# 共享常量
# ═══════════════════════════════════════════════════════════

HDR_REFERENCES = "## 参考信息\n\n"
HDR_GLOSSARY = "### 术语表\n"
HDR_FUZZY = "### 模糊匹配\n"

# ═══════════════════════════════════════════════════════════
# 键名前缀分组
# ═══════════════════════════════════════════════════════════

KEY_PREFIX_PROMPTS: dict[str, KeyPrefixConfig] = cfg.KEY_PREFIX_PROMPTS


def group_prefix(key: str) -> str:
    best = ""
    for prefix in KEY_PREFIX_PROMPTS:
        if key.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return best if best else DEFAULT_NAMESPACE


def prefix_config(key: str) -> KeyPrefixConfig:
    """返回 key 匹配键前缀的配置字典（未匹配返回空 dict）。"""
    return KEY_PREFIX_PROMPTS.get(group_prefix(key), {})


def is_batch_singleton(key: str) -> bool:
    """该 key 所属前缀是否要求逐条单独批处理（如长文本文档）。"""
    return prefix_config(key).get("batch_singleton", False)


def is_excluded_from_terminology(key: str) -> bool:
    """该 key 所属前缀是否应排除在术语提取之外。"""
    return prefix_config(key).get("exclude_terminology", False)


def classify_entries(entries: list[EntryDict]) -> GroupedEntries:
    groups: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        prefix = group_prefix(entry["key"])
        groups.setdefault(prefix, []).append(entry)  # type: ignore[arg-type]
    return groups


def classify_key(key: str) -> str:
    prefix = group_prefix(key)
    if prefix == DEFAULT_NAMESPACE:
        return "其他"
    return KEY_PREFIX_PROMPTS.get(prefix, {}).get("label", "其他")


# ═══════════════════════════════════════════════════════════
# 输入设备检测
# ═══════════════════════════════════════════════════════════

_RE_KEYBOARD_KEY = re.compile(r"\b(Shift|Ctrl|Alt|Tab)\b", re.IGNORECASE)

_RE_MOUSE_OP = re.compile(
    r"(?i)\b(?:left\s*click|right\s*click|left[- ]?mouse|right[- ]?mouse|"
    r"mouse\s*button|scroll\s*wheel|drag|double[-\s]?click|"
    r"middle\s*click|mouse\s*over|hover)\b|"
    r"(?:左键|右键|鼠标|单击|双击|点击|拖拽|滚轮)"
)


def detect_input_guidance(entries: list[EntryDict]) -> str:
    has_keyboard = False
    has_mouse = False
    for entry in entries:
        en = entry.get("en", "")
        zh = entry.get("zh", "")
        if not has_keyboard and _RE_KEYBOARD_KEY.search(en):
            has_keyboard = True
        if not has_mouse and _RE_MOUSE_OP.search(en + zh):
            has_mouse = True
        if has_keyboard and has_mouse:
            break
    parts: list[str] = []
    if has_keyboard:
        parts.append(cfg.KEYBOARD_GUIDANCE)
    if has_mouse:
        parts.append(cfg.MOUSE_GUIDANCE)
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# LLM 审校筛选器
# ═══════════════════════════════════════════════════════════

LLM_REQUIRED_PREFIXES: set[str] = cfg.LLM_REQUIRED_PREFIXES
LLM_REQUIRED_PATTERNS: list[str] = list(cfg.DESC_KEY_SUFFIXES) + [".title"]
_RE_GLOSSARY_GAP = re.compile(r"[ ,.!?;:'\"()\[\]{}<>\-_/%\t\n\r]+")


def needs_llm_review(entry: EntryDict) -> bool:
    key = entry["key"]
    if group_prefix(key) in LLM_REQUIRED_PREFIXES:
        return True
    for pattern in LLM_REQUIRED_PATTERNS:
        if pattern in key:
            return True
    if len(entry.get("en", "")) > 80:
        return True
    return False


def _is_glossary_covered(en: str, zh: str, glossary: list[GlossaryDict]) -> bool:
    if not glossary:
        return False
    en_lower = en.lower()
    hits: list[tuple[int, int, str]] = []
    sorted_glossary = sorted(glossary, key=lambda g: -len(g["en"]))
    for g in sorted_glossary:
        gen = g["en"].lower()
        start = 0
        while True:
            idx = en_lower.find(gen, start)
            if idx == -1:
                break
            hits.append((idx, idx + len(gen), g["zh"]))
            start = idx + 1
    if not hits:
        return False
    hits.sort(key=lambda h: h[0])
    pos = 0
    for start, end, _zh_val in hits:
        if start < pos:
            continue
        gap = en[pos:start]
        if _RE_GLOSSARY_GAP.sub("", gap):
            return False
        pos = end
    if _RE_GLOSSARY_GAP.sub("", en[pos:]):
        return False
    expected_parts: list[str] = []
    last_end = 0
    for start, end, zh_val in hits:
        if start >= last_end:
            expected_parts.append(zh_val)
            last_end = end
    return "".join(expected_parts) == zh


def filter_for_llm(
    matched_entries: list[EntryDict],
    auto_flagged_keys: set[str],
    glossary: list[GlossaryDict] | None = None,
) -> tuple[list[EntryDict], list[EntryDict]]:
    llm_entries: list[EntryDict] = []
    auto_pass: list[EntryDict] = []
    for entry in matched_entries:
        key = entry["key"]
        if key in auto_flagged_keys:
            llm_entries.append(entry)
            continue
        if needs_llm_review(entry):
            llm_entries.append(entry)
            continue
        if glossary:
            if not _is_glossary_covered(entry.get("en", ""), entry.get("zh", ""), glossary):
                llm_entries.append(entry)
                continue
        else:
            llm_entries.append(entry)
            continue
        auto_pass.append(entry)
    return llm_entries, auto_pass


# ═══════════════════════════════════════════════════════════
# 条目块构建
# ═══════════════════════════════════════════════════════════

def build_entry_block(
    entry: EntryDict,
    auto_verdicts: list[VerdictDict] | None = None,
    full_en: str = "",
    full_zh: str = "",
) -> str:
    key = entry["key"]
    en = full_en or entry.get("en", "")
    zh = full_zh or entry.get("zh", "")
    lines = [f"key: `{key}`"]

    en_label = "EN (完整上下文)" if full_en else "EN"
    zh_label = "ZH (完整上下文)" if full_en else "ZH"
    lines.append(f'{en_label}: "{en}"')
    lines.append(f'{zh_label}: "{zh}"')

    change = entry.get("_change")
    if change:
        if change.get("old_en"):
            lines.append(f'old_en: "{change["old_en"]}"')
        if change.get("old_zh"):
            lines.append(f'old_zh: "{change["old_zh"]}"')
        if change.get("ref_version"):
            lines.append("")
            lines.append("跨版本参考:")
            lines.append(f'  ref_version: {change["ref_version"]}')
            if change.get("ref_en"):
                lines.append(f'  ref_en: "{change["ref_en"]}"')
            if change.get("ref_zh"):
                lines.append(f'  ref_zh: "{change["ref_zh"]}"')

    if auto_verdicts:
        lines.append("")
        for v in auto_verdicts:
            lines.append(f"  自动检查: {v['verdict']} — {v['reason']}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 多段条目合并
# ═══════════════════════════════════════════════════════════

def merge_multipart_entries(entries: list[EntryDict]) -> MultipartContext:
    result: dict[str, tuple[str, str]] = {}
    for _base, group in iter_indexed_groups(entries):
        full_en = "".join(e.get("en", "") for e in group)
        full_zh = "".join(e.get("zh", "") for e in group)
        for e in group:
            result[e["key"]] = (full_en, full_zh)
    return result


# ═══════════════════════════════════════════════════════════
# Batch 隔离：三元组 (slug, version, namespace) 分组
# ═══════════════════════════════════════════════════════════


def _group_by_slug_ver_ns(
    entries: list[EntryDict],
) -> dict[tuple[str, str, str], list[EntryDict]]:
    """按 (slug, version, namespace) 三元组分组，保证 batch 不跨模组/版本/命名空间。"""
    groups: dict[tuple[str, str, str], list[EntryDict]] = {}
    for e in entries:
        slug = e.get("slug", "")
        ver = e.get("version", "")
        ns = e.get("namespace", "") or group_prefix(e["key"])
        key = (slug or "", ver or "", ns)
        groups.setdefault(key, []).append(e)
    return groups


# ═══════════════════════════════════════════════════════════
# 审校 Prompt
# ═══════════════════════════════════════════════════════════

def _build_batch_references(
    entries: list[EntryDict],
    glossary: list[GlossaryDict] | None = None,
    fuzzy_map: FuzzyResultsMap | None = None,
    dict_stores: list | None = None,
    merged_context: MultipartContext | None = None,
) -> str:
    """从全部条目构建 batch 级参考信息节。
    返回 "## 参考信息\\n\\n### 术语表\\n...\\n\\n### 模糊匹配\\n...\\n\\n### 原版词典\\n...\\n\\n### 词典\\n..."
    无数据时返回空串。
    """
    sections: list[str] = []

    # ── 术语表 ──
    if glossary:
        seen_term: set[str] = set()
        term_lines: list[str] = []
        for g in glossary:
            en_key = g["en"].lower()
            if en_key in seen_term:
                continue
            seen_term.add(en_key)
            term_lines.append(f'"{g["en"]}" → "{g["zh"]}"')
        if term_lines:
            sections.append(HDR_GLOSSARY + "\n".join(term_lines))

    # ── 模糊匹配 ──
    if fuzzy_map:
        batch_keys = {e["key"] for e in entries}
        seen_fuzzy: set[str] = set()
        fuzzy_lines: list[str] = []
        for key, results in fuzzy_map.items():
            if key not in batch_keys:
                continue
            for fr in results:
                sig = f"{key}|{fr['similarity']}|{fr.get('en','')[:60]}"
                if sig in seen_fuzzy:
                    continue
                seen_fuzzy.add(sig)
                fuzzy_lines.append(
                    f"[{key}] sim={fr['similarity']}% | "
                    f'EN: "{fr.get("en", "")[:100]}" | '
                    f'ZH: "{fr.get("zh", "")[:100]}"'
                )
        if fuzzy_lines:
            sections.append(HDR_FUZZY + "\n".join(fuzzy_lines))

    # ── 原版词典 + 词典 ──
    if dict_stores:
        for store in dict_stores:
            heading = getattr(store, "lookup_heading", "")
            mode = getattr(store, "default_lookup_mode", None)
            if not heading or mode is None:
                continue

            seen_store: set[str] = set()
            store_lines: list[str] = []
            for entry in entries:
                key = entry["key"]
                en_text = (merged_context or {}).get(key, ("", ""))[0] or entry.get("en", "")
                try:
                    hint = store.lookup(en_text, mode=mode, entry_key=key, version=entry.get("version"))
                except Exception:
                    continue
                if not hint:
                    continue
                for line in hint.split("\n"):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # strip known store-internal headers
                    for prefix_hdr in ("外部词典:", "原版词典："):
                        if stripped == prefix_hdr.strip():
                            stripped = ""
                            break
                    if not stripped:
                        continue
                    if stripped not in seen_store:
                        store_lines.append(stripped)
                        seen_store.add(stripped)

            if store_lines:
                sections.append(heading + "\n" + "\n".join(store_lines))

    if not sections:
        return ""
    return HDR_REFERENCES + "\n\n".join(sections)


def build_review_prompt(
    entries: list[EntryDict],
    glossary_entries: list[GlossaryDict] | None = None,
    auto_verdicts_map: AutoVerdictsMap | None = None,
    fuzzy_results_map: FuzzyResultsMap | None = None,
    batch_size: int = 25,
    merged_context: MultipartContext | None = None,
    dict_stores: list | None = None,
) -> list[str]:
    if not entries:
        return []

    # ── 1. 静态统一 header：从全部已知前缀构建 focus_notes，始终不变 ──
    focus_parts: list[str] = []
    for prefix in sorted(KEY_PREFIX_PROMPTS):
        info = KEY_PREFIX_PROMPTS[prefix]
        focus = info.get("focus", "")
        if focus and focus != cfg.DEFAULT_REVIEW_FOCUS:
            focus_parts.append(focus)
    merged_focus = "\n".join(focus_parts) or cfg.DEFAULT_REVIEW_FOCUS

    header = cfg.PROMPT_REVIEW_HEADER.format(
        header_prefix=cfg.REVIEW_HEADER_PREFIX,
        focus_notes=merged_focus,
        review_principles=cfg.REVIEW_PRINCIPLES,
    )

    # 以下 section 全部无条件拼接，保障 prompt 结构稳定以命中 KV cache
    header += cfg.PROMPT_REVIEW_PR_SECTION.format(
        change_context=cfg.get("pr_change_context_prompt", "")
    )
    header += cfg.PROMPT_CROSS_VERSION_REF_SECTION
    header += cfg.PROMPT_REVIEW_ITEMS_SECTION.format(
        count=len(entries),
        review_instruction=cfg.REVIEW_INSTRUCTION,
    )
    full_input_guidance = cfg.KEYBOARD_GUIDANCE + "\n" + cfg.MOUSE_GUIDANCE
    header += cfg.PROMPT_REVIEW_INPUT_DEVICE_SECTION.format(
        input_guidance=full_input_guidance,
    )

    # ── 2. 参考信息随数据变动，保留原写法 ──
    references = _build_batch_references(
        entries, glossary_entries, fuzzy_results_map, dict_stores, merged_context
    )

    # ── 3. 组装共享前缀 ──
    shared_prefix = f"{header}\n\n{references}" if references else header

    # ── 4. 三元组分组后，组内按 prefix/batch_size 切分 ──
    prompts: list[str] = []
    tri_groups = _group_by_slug_ver_ns(entries)

    for (_slug, _ver, _ns), group_entries in tri_groups.items():
        # 组内按 key prefix 再分组
        prefix_groups: dict[str, list[EntryDict]] = {}
        for e in group_entries:
            prefix = group_prefix(e["key"])
            prefix_groups.setdefault(prefix, []).append(e)

        for prefix, prefix_entries in prefix_groups.items():
            effective_bs = 1 if KEY_PREFIX_PROMPTS.get(prefix, {}).get("batch_singleton") else batch_size

            i = 0
            while i < len(prefix_entries):
                if is_batch_singleton(prefix_entries[i]["key"]):
                    batch = [prefix_entries[i]]
                    i += 1
                else:
                    batch = []
                    while i < len(prefix_entries) and len(batch) < effective_bs and not is_batch_singleton(prefix_entries[i]["key"]):
                        batch.append(prefix_entries[i])
                        i += 1

                batch_shared_prefix = shared_prefix

                blocks = [batch_shared_prefix]
                for e in batch:
                    key = e["key"]
                    auto_v = auto_verdicts_map.get(key, []) if auto_verdicts_map else []
                    full_en, full_zh = merged_context.get(key, ("", "")) if merged_context else ("", "")
                    block = build_entry_block(e, auto_v, full_en, full_zh)
                    blocks.append(block)
                prompts.append("\n\n".join(blocks))

    return prompts


# ═══════════════════════════════════════════════════════════
# Phase 5 过滤 Prompt
# ═══════════════════════════════════════════════════════════

def build_filter_prompt(
    verdicts: list[VerdictDict],
    batch_size: int = 50,
) -> list[str]:
    groups: dict[str, list[VerdictDict]] = {}
    for v in verdicts:
        key = v.get("key", "")
        prefix = group_prefix(key)
        groups.setdefault(prefix, []).append(v)

    prompts: list[str] = []
    for prefix, group_entries in groups.items():
        effective_batch = 1 if KEY_PREFIX_PROMPTS.get(prefix, {}).get("batch_singleton") else batch_size

        for i in range(0, len(group_entries), effective_batch):
            batch = group_entries[i:i + effective_batch]
            header = cfg.PROMPT_FILTER_HEADER.format(
                count=len(batch),
            )
            lines: list[str] = []
            for v in batch:
                key = v.get("key", "")
                en = v.get("en_current", "")
                zh = v.get("zh_current", "")
                verdict = v.get("verdict", "")
                reason = v.get("reason", "")
                suggestion = v.get("suggestion", "")
                is_singleton = is_batch_singleton(key)
                block = cfg.PROMPT_FILTER_ENTRY_BLOCK.format(
                    key=key,
                    en=en if is_singleton else en[:200],
                    zh=zh if is_singleton else zh[:200],
                    verdict=verdict,
                    reason=reason,
                )
                if suggestion:
                    block += "\n" + cfg.PROMPT_FILTER_ENTRY_SUGGESTION.format(suggestion=suggestion)
                lines.append(block)
            prompts.append(header + cfg.FILTER_INSTRUCTION + "\n\n" + "\n".join(lines))
    return prompts


# ═══════════════════════════════════════════════════════════
# 未翻译条目审校 Prompt
# ═══════════════════════════════════════════════════════════

def build_untranslated_prompt(entries: list[EntryDict], batch_size: int = 1) -> list[str]:
    """为疑似未翻译条目（en == zh）构建审校 prompt 列表。按 batch_size 分组。"""
    prompts: list[str] = []
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]
        blocks: list[str] = []
        for entry in batch:
            key = entry["key"]
            en = entry.get("en", "")
            zh = entry.get("zh", "")
            blocks.append(f"key: `{key}`\nEN: \"{en}\"\nZH: \"{zh}\"\n")
        prompt = cfg.PROMPT_UNTRANSLATED.format(count=len(batch))
        prompt += "\n\n" + "\n".join(blocks) + "\n仅输出JSON数组。"
        prompts.append(prompt)
    return prompts
