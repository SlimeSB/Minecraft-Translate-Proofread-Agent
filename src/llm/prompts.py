"""LLM 提示词构建器。

包含：条目分类、审校提示词、Phase 5 过滤提示词、术语覆盖率检查。
"""
import re

from src import config as cfg
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
# 键名前缀分组
# ═══════════════════════════════════════════════════════════

KEY_PREFIX_PROMPTS: dict[str, KeyPrefixConfig] = cfg.KEY_PREFIX_PROMPTS


def group_prefix(key: str) -> str:
    best = ""
    for prefix in KEY_PREFIX_PROMPTS:
        if key.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return best if best else "__default__"


def classify_entries(entries: list[EntryDict]) -> GroupedEntries:
    groups: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        key = entry["key"]
        if key.startswith("ae2guide:"):
            prefix = "ae2guide:"
        else:
            prefix = group_prefix(key)
        groups.setdefault(prefix, []).append(entry)
    return groups


def classify_key(key: str) -> str:
    prefix = group_prefix(key)
    if prefix == "__default__":
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

STYLE_REFERENCE = ""  # 暂无风格参考，可通过 llm.style_reference 配置


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
        if glossary and not _is_glossary_covered(entry.get("en", ""), entry.get("zh", ""), glossary):
            llm_entries.append(entry)
            continue
        auto_pass.append(entry)
    return llm_entries, auto_pass


# ═══════════════════════════════════════════════════════════
# 条目块构建
# ═══════════════════════════════════════════════════════════

def build_entry_block(
    entry: EntryDict,
    index: int = 0,
    fuzzy_results: list[FuzzyResultDict] | None = None,
    auto_verdicts: list[VerdictDict] | None = None,
    glossary_entries: list[GlossaryDict] | None = None,
    full_en: str = "",
    full_zh: str = "",
    external_hints: str = "",
) -> str:
    key = entry["key"]
    en = full_en or entry.get("en", "")
    zh = full_zh or entry.get("zh", "")
    lines = [f"key: `{key}`"]
    is_guideme = key.startswith("ae2guide:")
    if full_en:
        en_s = en if is_guideme else en[:600]
        zh_s = zh if is_guideme else zh[:600]
        lines.append(f'EN (完整上下文): "{en_s}"')
        lines.append(f'ZH (完整上下文): "{zh_s}"')
    else:
        en_s = en if is_guideme else en[:300]
        zh_s = zh if is_guideme else zh[:300]
        lines.append(f'EN: "{en_s}"')
        lines.append(f'ZH: "{zh_s}"')
    change = entry.get("_change")
    if change:
        if change.get("old_en"):
            lines.append(f'old_en: "{change["old_en"][:300]}"')
        if change.get("old_zh"):
            lines.append(f'old_zh: "{change["old_zh"][:300]}"')
    if auto_verdicts:
        lines.append("")
        for v in auto_verdicts:
            lines.append(f"  自动检查: {v['verdict']} — {v['reason']}")
    if fuzzy_results:
        lines.append("  模糊匹配:")
        for fr in fuzzy_results[:3]:
            lines.append(f"    sim={fr['similarity']}% | EN: \"{fr['en'][:100]}\" | ZH: \"{fr['zh'][:100]}\"")
    if glossary_entries:
        en_lower = en.lower()
        hints: list[str] = []
        for g in glossary_entries:
            if g["en"].lower() in en_lower:
                hints.append(f"\"{g['en']}\" → \"{g['zh']}\"")
        if hints:
            lines.append(f"  术语: {', '.join(hints[:5])}")
    if external_hints:
        lines.append(external_hints)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 多段条目合并
# ═══════════════════════════════════════════════════════════

_RE_MULTIPART = re.compile(r"^(.*)\.(\d+)$")


def merge_multipart_entries(entries: list[EntryDict]) -> MultipartContext:
    groups: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        m = _RE_MULTIPART.match(entry["key"])
        if m:
            base = m.group(1)
            groups.setdefault(base, []).append(entry)
    result: dict[str, tuple[str, str]] = {}
    for base, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda e: int(_RE_MULTIPART.match(e["key"]).group(2)))
        full_en = "".join(e.get("en", "") for e in group)
        full_zh = "".join(e.get("zh", "") for e in group)
        for e in group:
            result[e["key"]] = (full_en, full_zh)
    return result


# ═══════════════════════════════════════════════════════════
# 审校 Prompt
# ═══════════════════════════════════════════════════════════

def build_review_prompt(
    entries: list[EntryDict],
    glossary_entries: list[GlossaryDict] | None = None,
    auto_verdicts_map: AutoVerdictsMap | None = None,
    fuzzy_results_map: FuzzyResultsMap | None = None,
    batch_size: int = 20,
    merged_context: MultipartContext | None = None,
    external_dict_store: object = None,
) -> list[str]:
    prompts: list[str] = []
    groups = classify_entries(entries)
    for prefix, group_entries in groups.items():
        info = KEY_PREFIX_PROMPTS.get(prefix, {})
        cat_label = info.get("label", "其他")
        focus_notes = info.get("focus", cfg.DEFAULT_REVIEW_FOCUS)
        effective_batch = 1 if prefix == "ae2guide:" else batch_size
        for i in range(0, len(group_entries), effective_batch):
            batch = group_entries[i:i + effective_batch]
            header = f"""{cfg.REVIEW_HEADER_PREFIX}。当前类型: {cat_label}（{prefix}*）。

## 审查重点
{focus_notes}

## 风格参考
{STYLE_REFERENCE}

## 普适原则
{cfg.REVIEW_PRINCIPLES}
"""
            has_change = any(
                entry.get("_change", {}).get("old_en") or entry.get("_change", {}).get("old_zh")
                for entry in batch
            )
            if has_change:
                header += f"\n## PR 模式审校指南\n{cfg.get('pr_change_context_prompt', '')}\n"
            header += f"\n## 待审条目 ({len(batch)}条)\n"
            header += cfg.REVIEW_INSTRUCTION + "\n"
            input_guidance = detect_input_guidance(batch)
            if input_guidance:
                header += f"\n## 输入设备翻译专项指南\n{input_guidance}\n"
            blocks = [header]
            for j, entry in enumerate(batch):
                key = entry["key"]
                auto_v = auto_verdicts_map.get(key, []) if auto_verdicts_map else []
                fuzzy_r = fuzzy_results_map.get(key, []) if fuzzy_results_map else []
                full_en, full_zh = merged_context.get(key, ("", "")) if merged_context else ("", "")
                en_for_hints = full_en or entry.get("en", "")
                external_hints = external_dict_store.lookup(en_for_hints) if external_dict_store else ""
                block = build_entry_block(entry, j + 1, fuzzy_r, auto_v, glossary_entries, full_en, full_zh, external_hints=external_hints)
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
        info = KEY_PREFIX_PROMPTS.get(prefix, {})
        cat_label = info.get("label", "其他")
        effective_batch = 1 if prefix == "ae2guide:" else batch_size

        for i in range(0, len(group_entries), effective_batch):
            batch = group_entries[i:i + effective_batch]
            header = f"""## 任务
以下是自动检查和LLM审校后汇总的翻译问题列表（{cat_label}）。请逐条判断每条是否需要驳回（不提出），需要保留的清洗其问题描述。

## 问题列表 ({len(batch)}条)
"""
            lines: list[str] = []
            for j, v in enumerate(batch):
                key = v.get("key", "")
                en = v.get("en_current", "")
                zh = v.get("zh_current", "")
                verdict = v.get("verdict", "")
                reason = v.get("reason", "")
                suggestion = v.get("suggestion", "")
                is_guideme = key.startswith("ae2guide:")
                block = f"### 条目 {j+1}\n"
                block += f"key: `{key}`\n"
                block += f'EN: "{en if is_guideme else en[:200]}"\n'
                block += f'ZH: "{zh if is_guideme else zh[:200]}"\n'
                block += f"判定: {verdict}\n"
                block += f"问题: {reason}\n"
                if suggestion:
                    block += f"建议: {suggestion}\n"
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
        for j, entry in enumerate(batch):
            key = entry["key"]
            en = entry.get("en", "")
            zh = entry.get("zh", "")
            blocks.append(f"key: `{key}`\nEN: \"{en}\"\nZH: \"{zh}\"\n")
        prompt = f"""你是Minecraft模组翻译审校专家。以下条目的英文和中文值相同（或高度相似），请判断是否确实为未翻译，还是合法的不需翻译的内容。

## 判定标准
- 原文为自然语言文本（单词、短语、句子），中文本应翻译但没有翻译 → 确实未翻译，判定 ❌ FAIL 并给出建议译文
- 原文为代码、版本号、数字、URL路径、占位符、专有名词、色彩代码、命令参数等，中英一致是合理的 → 合法不需翻译，判定 PASS

## 输出格式
对每条输出: {{"key": "条目的key值", "verdict": "PASS/❌ FAIL", "suggestion": "建议译文或空字符串", "reason": "判定理由"}}
PASS条目不输出。仅输出JSON数组。

## 条目 ({len(batch)}条)

""" + "\n".join(blocks) + "\n仅输出JSON数组。"
        prompts.append(prompt)
    return prompts
