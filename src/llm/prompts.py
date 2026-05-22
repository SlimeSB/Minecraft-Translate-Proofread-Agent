"""LLM 提示词构建器。

包含：条目分类、审校提示词、Phase 5 过滤提示词、术语覆盖率检查。
"""
import re

from src import config as cfg
from src.config import DEFAULT_NAMESPACE
from src.logging import debug
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
    MultipartContext,
    VerdictDict,
)

# ═══════════════════════════════════════════════════════════
# 手册格式检测
# ═══════════════════════════════════════════════════════════


def _get_manual_format_info(key: str) -> dict[str, str] | None:
    """匹配 key 所属的手册格式。返回 {dir_name, label} 或 None。"""
    for dir_name, info in cfg.MANUAL_FORMATS.items():
        prefix = f"{dir_name}:"
        if key.startswith(prefix):
            return {"dir_name": dir_name, "label": info.get("label", dir_name)}
    return None


def is_manual_format(key: str) -> bool:
    return _get_manual_format_info(key) is not None


def should_singleton(key: str, en_text: str = "") -> bool:
    if is_manual_format(key):
        return True
    if en_text and len(en_text) > cfg.SINGLETON_LENGTH_THRESHOLD:
        return True
    return False


def is_excluded_from_terminology(key: str) -> bool:
    return is_manual_format(key)


def manual_format_label(key: str) -> str:
    info = _get_manual_format_info(key)
    if info:
        return info["label"]
    return ""


def classify_key(key: str) -> str:
    """返回 key 的手册格式标签；非手册条目返回空字符串。"""
    return manual_format_label(key)


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

LLM_REQUIRED_PATTERNS: list[str] = list(cfg.DESC_KEY_SUFFIXES) + [".title"]
_RE_GLOSSARY_GAP = re.compile(r"[ ,.!?;:'\"()\[\]{}<>\-_/%\t\n\r]+")


def needs_llm_review(entry: EntryDict) -> bool:
    key = entry["key"]
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
    reason_auto_flagged = 0
    reason_llm_required = 0
    reason_glossary_uncovered = 0
    reason_auto_pass = 0
    for entry in matched_entries:
        key = entry["key"]
        if key in auto_flagged_keys:
            llm_entries.append(entry)
            reason_auto_flagged += 1
            debug(f"  [筛选·入选] {key}: 自动检查标记 → 送LLM")
            continue
        if needs_llm_review(entry):
            llm_entries.append(entry)
            reason_llm_required += 1
            reason_hint = "长文本" if len(entry.get("en", "")) > 80 else "必要前缀/.desc/.title"
            debug(f"  [筛选·入选] {key}: LLM要求 ({reason_hint}) → 送LLM")
            continue
        if glossary:
            if not _is_glossary_covered(entry.get("en", ""), entry.get("zh", ""), glossary):
                llm_entries.append(entry)
                reason_glossary_uncovered += 1
                debug(f"  [筛选·入选] {key}: 术语表未覆盖 → 送LLM")
                continue
        else:
            llm_entries.append(entry)
            reason_glossary_uncovered += 1
            debug(f"  [筛选·入选] {key}: 无术语表 → 送LLM")
            continue
        auto_pass.append(entry)
        reason_auto_pass += 1
    debug(f"  [筛选] 统计: 自动标记={reason_auto_flagged} LLM要求={reason_llm_required} 术语未覆盖={reason_glossary_uncovered} 自动通过={reason_auto_pass}")
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
    lines = [cfg.PROMPT_ENTRY_KEY_LINE.format(key=key)]

    en_label = cfg.ENTRY_EN_CONTEXT_LABEL if full_en else cfg.ENTRY_EN_LABEL
    zh_label = cfg.ENTRY_ZH_CONTEXT_LABEL if full_en else cfg.ENTRY_ZH_LABEL
    lines.append(cfg.PROMPT_ENTRY_EN_LINE.format(en_label=en_label, en=en))
    lines.append(cfg.PROMPT_ENTRY_EN_LINE.format(en_label=zh_label, en=zh))

    change = entry.get("_change")
    if change:
        if change.get("old_en"):
            lines.append(cfg.PROMPT_ENTRY_OLD_EN_LINE.format(old_en=change["old_en"]))
        if change.get("old_zh"):
            lines.append(cfg.PROMPT_ENTRY_OLD_ZH_LINE.format(old_zh=change["old_zh"]))
        if change.get("ref_version"):
            ref_extra_parts = []
            if change.get("ref_en"):
                ref_extra_parts.append(cfg.PROMPT_ENTRY_REF_EN_LINE.format(ref_en=change["ref_en"]))
            if change.get("ref_zh"):
                ref_extra_parts.append(cfg.PROMPT_ENTRY_REF_ZH_LINE.format(ref_zh=change["ref_zh"]))
            ref_extra = "\n".join(ref_extra_parts)
            lines.append(cfg.PROMPT_CROSS_VERSION_REF_BLOCK.format(
                ref_version=change["ref_version"],
                ref_extra=ref_extra,
            ))

    if auto_verdicts:
        lines.append("")
        for v in auto_verdicts:
            lines.append(cfg.PROMPT_AUTO_CHECK_LINE.format(
                verdict=v["verdict"],
                reason=v["reason"],
            ))
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
        ns = e.get("namespace", "") or ""
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
            term_lines.append(cfg.PROMPT_GLOSSARY_TERM_LINE.format(
                en=g["en"], zh=g["zh"]
            ))
        if term_lines:
            sections.append(cfg.PROMPT_GLOSSARY_SECTION.format(
                glossary_entries="\n".join(term_lines)
            ))

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
                    cfg.PROMPT_FUZZY_MATCH_LINE.format(
                        key=key,
                        similarity=fr["similarity"],
                        en=fr.get("en", "")[:100],
                        zh=fr.get("zh", "")[:100],
                    )
                )
        if fuzzy_lines:
            sections.append(cfg.PROMPT_FUZZY_SECTION.format(
                fuzzy_entries="\n".join(fuzzy_lines)
            ))

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
                    for prefix_hdr in cfg.DICT_STORE_HEADERS_TO_STRIP:
                        if stripped == prefix_hdr.strip():
                            stripped = ""
                            break
                    if not stripped:
                        continue
                    if stripped not in seen_store:
                        store_lines.append(stripped)
                        seen_store.add(stripped)

            if store_lines:
                sections.append(cfg.PROMPT_DICT_SECTION.format(
                    dict_heading=heading,
                    dict_entries="\n".join(store_lines),
                ))

    if not sections:
        return ""
    return cfg.PROMPT_REFERENCE_SECTION.format(
        sections="\n\n".join(sections)
    )


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

    # ── 1. 静态统一 header：使用默认审校重点 ──
    header = cfg.PROMPT_REVIEW_FULL_HEADER.format(
        header_prefix=cfg.REVIEW_HEADER_PREFIX,
        focus_notes=cfg.DEFAULT_REVIEW_FOCUS,
        review_principles=cfg.REVIEW_PRINCIPLES,
        change_context=cfg.get("pr_change_context_prompt", ""),
        count=len(entries),
        review_instruction=cfg.REVIEW_INSTRUCTION,
        keyboard_guidance=cfg.KEYBOARD_GUIDANCE,
        mouse_guidance=cfg.MOUSE_GUIDANCE,
    )

    # ── 2. 参考信息随数据变动，保留原写法 ──
    references = _build_batch_references(
        entries, glossary_entries, fuzzy_results_map, dict_stores, merged_context
    )

    # ── 3. 组装共享前缀 ──
    shared_prefix = cfg.PROMPT_HEADER_WITH_REFS.format(header=header, references=references) if references else header

    # ── 4. 三元组分组后，组内按 prefix/batch_size 切分 ──
    prompts: list[str] = []
    tri_groups = _group_by_slug_ver_ns(entries)

    for (_slug, _ver, _ns), group_entries in tri_groups.items():
        # 组内按手册格式再分组（手册格式单独批处理，普通条目按 batch_size 切分）
        format_groups: dict[str, list[EntryDict]] = {}
        for e in group_entries:
            mf_info = _get_manual_format_info(e["key"])
            fg = mf_info["dir_name"] if mf_info else DEFAULT_NAMESPACE
            format_groups.setdefault(fg, []).append(e)

        for fg, fg_entries in format_groups.items():
            i = 0
            while i < len(fg_entries):
                if should_singleton(fg_entries[i]["key"], fg_entries[i].get("en", "")):
                    batch = [fg_entries[i]]
                    i += 1
                else:
                    batch = []
                    while i < len(fg_entries) and len(batch) < batch_size and not should_singleton(fg_entries[i]["key"], fg_entries[i].get("en", "")):
                        batch.append(fg_entries[i])
                        i += 1

                batch_shared_prefix = shared_prefix

                blocks = [batch_shared_prefix]
                for e in batch:
                    key = e["key"]
                    auto_v = auto_verdicts_map.get(key, []) if auto_verdicts_map else []
                    full_en, full_zh = merged_context.get(key, ("", "")) if merged_context else ("", "")
                    block = build_entry_block(e, auto_v, full_en, full_zh)
                    blocks.append(block)
                prompts.append(cfg.PROMPT_BLOCK_SEPARATOR.join(blocks))

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
        mf_info = _get_manual_format_info(key)
        fg = mf_info["dir_name"] if mf_info else DEFAULT_NAMESPACE
        groups.setdefault(fg, []).append(v)

    prompts: list[str] = []
    for fg, group_entries in groups.items():
        effective_batch = 1 if fg != DEFAULT_NAMESPACE else batch_size

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
                is_singleton = should_singleton(key, en)
                block = cfg.PROMPT_FILTER_ENTRY_BLOCK.format(
                    key=key,
                    en=en if is_singleton else en[:200],
                    zh=zh if is_singleton else zh[:200],
                    verdict=verdict,
                    reason=reason,
                )
                if suggestion:
                    suggestion_text = cfg.PROMPT_FILTER_ENTRY_SUGGESTION.format(suggestion=suggestion)
                    block = cfg.PROMPT_FILTER_BLOCK_WITH_SUGGESTION.format(block=block, suggestion=suggestion_text)
                lines.append(block)
            prompts.append(cfg.PROMPT_FILTER_ASSEMBLY.format(
                header=header,
                instruction=cfg.FILTER_INSTRUCTION,
                entry_blocks="\n".join(lines),
            ))
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
            blocks.append(cfg.PROMPT_UNTRANSLATED_ENTRY_BLOCK.format(
                key=entry["key"],
                en=entry.get("en", ""),
                zh=entry.get("zh", ""),
            ))
        prompt = cfg.PROMPT_UNTRANSLATED.format(
            count=len(batch),
            entry_blocks="\n".join(blocks),
        )
        prompts.append(prompt)
    return prompts
