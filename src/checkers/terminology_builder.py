"""术语构建与匹配器：从 en_us.json 提取术语、词形归并、构建术语表、
检查翻译一致性。

归并策略: 规则分桶 → inflection 名词单数归一化归并

用法:
    from terminology_builder import TerminologyBuilder, llm_verify_glossary, check_consistency
    tb = TerminologyBuilder()
    tb.load(en_data, zh_data, alignment)
    glossary = tb.merge_and_build()
    glossary = llm_verify_glossary(glossary, tb.en_data, tb.zh_data, my_llm_fn)
    verdicts = check_consistency(glossary, tb.matched_entries, tb.merged)
"""
import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from src.logging import info, warn
from src.models import AlignmentDict, EntryDict, GlossaryDict, SOURCE_TERMINOLOGY_CHECK, VerdictDict
from src.tools.terminology_extract import extract_terms
from src import config as cfg
from .lemma_merge import (
    raw_merge,
    inflection_lemmatize_term,
    inflection_merge,
    try_rescue_short_term,
)
from src.tools.term_validation import is_valid_term, is_music_disc_desc


# ═══════════════════════════════════════════════════════════
# 公共中文提取
# ═══════════════════════════════════════════════════════════

def _find_common_substr(zh_counter: Counter, min_ratio: float) -> str | None:
    """在所有中文译文中找到最长公共子串（任意位置），需覆盖 ≥ min_ratio 比例的译文。

    例如 {"蜜蜂头套":1, "黑色绵羊头套":1, "兔兔头套":1, ...}
    → "头套" 出现在所有译文中 → 返回 "头套"。
    """
    zh_values = list(zh_counter.keys())
    if len(zh_values) < 2:
        return None
    total = len(zh_values)
    min_count = total * min_ratio
    shortest = min(zh_values, key=len)
    for length in range(len(shortest), 1, -1):
        seen: set[str] = set()
        for start in range(len(shortest) - length + 1):
            sub = shortest[start:start + length]
            if sub in seen:
                continue
            seen.add(sub)
            count = sum(1 for zh in zh_values if sub in zh)
            if count >= min_count:
                return sub
    return None


def _extract_common_zh(zh_counter: Counter, min_ratio: float) -> str | None:
    """从多个中文译文中提取公共子串，忽略离群值。

    先尝试整条译文作为子串匹配（如 "方铅岩" 出现在 "方铅岩砖" 中），
    失败时回退到任意位置公共子串搜索。

    例如 {"方铅岩":1, "方铅岩砖":2, "方铅岩台阶":1, "方前言":1}
    → "方铅岩" 出现在 "方铅岩砖" 和 "方铅岩台阶" 中（不含自身），覆盖 3/5=60% → 返回 "方铅岩"。
    """
    if len(zh_counter) < 2:
        return None
    total = sum(zh_counter.values())
    best = ""
    for zh in zh_counter:
        if len(zh) < 2:
            continue
        # 只统计其他 zh（不含自身）中包含此 zh 作为子串的频次
        support = sum(
            count for other, count in zh_counter.items()
            if other != zh and zh in other
        )
        if support / total >= min_ratio and len(zh) > len(best):
            best = zh
    if best:
        return best
    return _find_common_substr(zh_counter, min_ratio)


# ═══════════════════════════════════════════════════════════
# 术语表构建器
# ═══════════════════════════════════════════════════════════

def _parse_glossary_corrections(response: str) -> dict[str, dict[str, str]]:
    """解析 LLM 返回的术语修正 JSON 数组。"""
    from src.llm.bridge import parse_llm_json
    arr = parse_llm_json(response, extract_code_block=True)
    result = {}
    for item in arr:
        if not isinstance(item, dict):
            continue
        en = (item.get("en") or "").lower().strip()
        new_zh = item.get("new_zh", "").strip()
        if en and new_zh:
            result[en] = {"new_zh": new_zh}
    return result


# ═══════════════════════════════════════════════════════════
# build_glossary() 拆分出的三个子函数
# ═══════════════════════════════════════════════════════════


def _clean_zh_for_glossary(zh: str) -> str:
    zh = re.sub(r"%(\d+\$)?[+-]?\d*\.?\d*[dsf]", "", zh)
    zh = zh.strip(cfg.ZH_GLOSSARY_STRIP_PUNCTUATION)
    zh = zh.strip()
    return zh


def _collect_zh_translations(
    merged: dict[str, dict[str, Any]],
    matched_entries: list[EntryDict],
    min_freq: int,
    min_consensus: float,
    min_total: int,
    max_zh_len: int,
    max_en_len: int,
) -> list[GlossaryDict]:
    """从 matched_entries 统计每组术语的中文译文，构建初始术语表。"""
    glossary: list[GlossaryDict] = []
    stats = {"total": 0, "keys_fail": 0, "valid_fail": 0, "no_zh": 0, "total_fail": 0, "consensus_fail": 0, "pass": 0}
    for norm, bucket in sorted(merged.items(), key=lambda x: -len(x[1]["keys"])):
        stats["total"] += 1
        n_keys = len(bucket["keys"])
        if n_keys < min_freq:
            stats["keys_fail"] += 1
            continue
        if not is_valid_term(norm):
            stats["valid_fail"] += 1
            continue

        zh_counter: Counter = Counter()
        skipped_no_entry = 0
        skipped_desc = 0
        skipped_empty_or_long = 0
        skipped_variant_mismatch = 0
        for k in bucket["keys"]:
            entry = next((e for e in matched_entries if e["key"] == k), None)
            if not entry:
                skipped_no_entry += 1
                continue
            if any(p in k for p in cfg.DESC_KEY_SUFFIXES):
                skipped_desc += 1
                continue
            zh_val = _clean_zh_for_glossary(entry.get("zh", ""))
            en_val = entry.get("en", "")
            if not zh_val or zh_val == en_val or len(zh_val) > max_zh_len or len(en_val) > max_en_len:
                skipped_empty_or_long += 1
                continue
            variants = bucket["variants"]
            if not any(re.search(r"\b" + re.escape(v) + r"\b", en_val, re.IGNORECASE) for v in variants):
                skipped_variant_mismatch += 1
                continue
            zh_counter[zh_val[:120]] += 1

        if not zh_counter:
            stats["no_zh"] += 1
            warn(f"  [术语表·无ZH] \"{norm}\": keys={n_keys}, "
                 f"no_entry={skipped_no_entry} desc={skipped_desc} "
                 f"empty_or_long={skipped_empty_or_long} variant_mismatch={skipped_variant_mismatch}")
            continue

        best_zh, best_count = zh_counter.most_common(1)[0]
        total = sum(zh_counter.values())
        variants = sorted(bucket["variants"], key=len)
        en_term = variants[0] if variants else norm
        if total >= min_total and best_count / total >= min_consensus:
            stats["pass"] += 1
            glossary.append({"en": en_term, "zh": best_zh})
        elif total >= min_total:
            common = _extract_common_zh(zh_counter, min_consensus)
            if common:
                stats["pass"] += 1
                glossary.append({"en": en_term, "zh": common})
            else:
                stats["consensus_fail"] += 1
                warn(f"  [术语表·共识不足] \"{en_term}\": {len(zh_counter)} 种不同译文, "
                     f"共识 {best_count}/{total}={best_count/total:.0%}, 公共子串空, "
                     f"keys={n_keys}, no_entry={skipped_no_entry} desc={skipped_desc} "
                     f"empty_or_long={skipped_empty_or_long} variant_mismatch={skipped_variant_mismatch}")
        else:
            stats["total_fail"] += 1
            warn(f"  [术语表·总数不足] \"{en_term}\": total={total} < min_total={min_total}, "
                 f"keys={n_keys}, no_entry={skipped_no_entry} desc={skipped_desc} "
                 f"empty_or_long={skipped_empty_or_long} variant_mismatch={skipped_variant_mismatch}")

    info(f"  [术语表] 统计: 总数={stats['total']}, "
         f"keys不足(<{min_freq})={stats['keys_fail']}, 无效术语={stats['valid_fail']}, "
         f"无ZH={stats['no_zh']}, 总数不足(<{min_total})={stats['total_fail']}, "
         f"共识不足={stats['consensus_fail']}, 通过={stats['pass']}")
    return glossary


def _dedup_zh_conflicts(
    glossary: list[GlossaryDict],
    merged: dict[str, dict[str, Any]],
    matched_entries: list[EntryDict],
) -> list[GlossaryDict]:
    """中文互斥去重：同一中文对应多个英文术语时，给短术语第二次机会。"""
    before_dedup = len(glossary)
    zh_to_entries: dict[str, list[GlossaryDict]] = {}
    for item in glossary:
        zh_to_entries.setdefault(item["zh"], []).append(item)
    glossary = []
    removed_count = 0
    rescued_count = 0
    for zh_val, items in zh_to_entries.items():
        if len(items) == 1:
            glossary.append(items[0])
            continue
        sorted_items = sorted(items, key=lambda x: len(x["en"]), reverse=True)
        to_remove: list[GlossaryDict] = []
        for i, item_a in enumerate(sorted_items):
            en_a_l = item_a["en"].lower()
            for j in range(i + 1, len(sorted_items)):
                item_b = sorted_items[j]
                en_b_l = item_b["en"].lower()
                if en_b_l in en_a_l and item_b not in to_remove:
                    rescued = try_rescue_short_term(item_b, item_a, merged, matched_entries)  # type: ignore[arg-type]
                    if rescued:
                        glossary.append(rescued)  # type: ignore[arg-type]
                        rescued_count += 1
                    else:
                        to_remove.append(item_b)
                        removed_count += 1
        for item in sorted_items:
            if item not in to_remove:
                glossary.append(item)
    if removed_count or rescued_count:
        msg = f"  [术语表] 中文互斥: {before_dedup} → {len(glossary)} 条（移除 {removed_count} 条子串冲突"
        if rescued_count:
            msg += f", 救回 {rescued_count} 条（剔除长术语key后指向不同中文）"
        msg += "）"
        info(msg)
    return glossary


# ═══════════════════════════════════════════════════════════
# 模块级校验与检查函数
# ═══════════════════════════════════════════════════════════

def llm_verify_glossary(
    glossary: Sequence[GlossaryDict],
    en_data: dict[str, str],
    zh_data: dict[str, str],
    llm_call: Callable[[str], str] | None,
    term_hints: dict[str, str] | None = None,
) -> list[GlossaryDict]:
    """LLM 校验术语表: 每条术语取 1 最长 + 4 最短含术语原文, 交 LLM 复核。

    Args:
        glossary: 术语表列表，每项含 "en" 和 "zh" 键
        en_data: 英文条目数据 (key -> en text)
        zh_data: 中文条目数据 (key -> zh text)
        llm_call: LLM 调用函数
        term_hints: 预计算的词典参考，key 为术语英文原文小写，value 为已拼接提示文本

    Returns:
        修正后的术语表（与传入的 glossary 为同一列表对象）
    """
    if not glossary or not llm_call:
        return glossary

    import re
    term_sources: dict[str, list[tuple[str, str]]] = {}
    for g in glossary:
        en_lower = g["en"].lower()
        term_sources[en_lower] = []
        seen_en: set[str] = set()
        for key, en_val in en_data.items():
            if not isinstance(en_val, str):
                continue
            if en_val in seen_en:
                continue
            if re.search(r"\b" + re.escape(en_lower) + r"\b", en_val, re.IGNORECASE):
                seen_en.add(en_val)
                zh_val = zh_data.get(key, "")
                term_sources[en_lower].append((en_val, zh_val))

    lines: list[str] = []
    verify_items: list[GlossaryDict] = []
    for g in glossary:
        en_lower = g["en"].lower()
        sources = term_sources.get(en_lower, [])
        if not sources:
            continue
        if len(sources) < 2:
            continue
        sorted_sources = sorted(sources, key=lambda x: len(x[0]))
        ctx = [sorted_sources[-1]] + sorted_sources[:4]
        block = cfg.PROMPT_TERM_VERIFY_TERM_LINE.format(en=g["en"], zh=g["zh"])
        for j, (en_txt, zh_txt) in enumerate(ctx):
            block += cfg.PROMPT_TERM_VERIFY_CTX_LINE.format(index=j + 1, en=en_txt, zh=zh_txt)
        if term_hints:
            hint = term_hints.get(en_lower, "")
            if hint:
                block += "\n" + hint
        lines.append(block)
        verify_items.append(g)

    if not verify_items:
        return glossary

    prompt = cfg.PROMPT_TERM_VERIFICATION.format(
        term_blocks="\n\n".join(lines)
    )

    try:
        response = llm_call(prompt)
        corrections = _parse_glossary_corrections(response)
    except Exception as e:
        warn(f"[术语校验] LLM 术语校验调用异常: {type(e).__name__}: {e}")
        return glossary

    if not corrections:
        return glossary

    corrected = 0
    for g in glossary:
        corr = corrections.get(g["en"].lower())
        if corr:
            g["zh"] = corr["new_zh"]
            corrected += 1

    if corrected:
        info(f"  [术语表] LLM校验: 修正 {corrected}/{len(verify_items)} 条术语")

    return glossary


def check_consistency(
    glossary: Sequence[GlossaryDict],
    matched_entries: Sequence[EntryDict],
    merged: dict[str, dict[str, Any]] | None = None,
) -> list[VerdictDict]:
    """用术语表检查 matched_entries 中的翻译一致性。
    按词边界匹配（避免子串误匹配：eat 不匹配 Defeat）。
    唱片名（music_disc.*.desc）跳过不检查。

    Args:
        glossary: 术语表列表，每项含 "en" 和 "zh" 键
        matched_entries: 已对齐条目列表
        merged: 词形归并桶（可选），用于变体展开。None 时仅使用 glossary en 值。

    Returns:
        Verdict 列表
    """
    if not glossary:
        return []

    import re

    term_info: list[tuple[str, str, re.Pattern]] = []
    for g in glossary:
        en_lower = g["en"].lower()
        if merged is not None and en_lower in merged:
            variants = sorted(merged[en_lower]["variants"], key=len)
        else:
            variants = [g["en"]]
        patterns = [re.escape(v.lower()) for v in variants]
        combined = r"\b(?:" + "|".join(patterns) + r")\b"
        term_info.append((g["en"], g["zh"], re.compile(combined, re.IGNORECASE)))

    verdicts: list[VerdictDict] = []
    for entry in matched_entries:
        key = entry["key"]
        en = entry.get("en", "")
        zh = entry.get("zh", "")
        if not isinstance(en, str) or not isinstance(zh, str) or not zh.strip():
            continue

        if is_music_disc_desc(key):
            continue

        for en_term, std_zh, pattern in term_info:
            if not pattern.search(en):
                continue
            if std_zh in zh:
                continue
            verdicts.append({
                "key": key,
                "en_current": en,
                "zh_current": zh,
                "verdict": "❌ FAIL",
                "suggestion": std_zh,
                "reason": f'术语不一致——“{en_term}”在术语表中译为“{std_zh}”，此处未使用',
                "source": SOURCE_TERMINOLOGY_CHECK,
            })

    return verdicts


class TerminologyBuilder:
    """术语提取、归并、匹配的完整流水线。"""

    def __init__(self):
        self.en_data: dict[str, str] = {}
        self.zh_data: dict[str, str] = {}
        self.matched_entries: list[EntryDict] = []
        self.extracted: dict[str, Any] = {}
        self.glossary: list[GlossaryDict] = []
        self.merged: dict[str, dict[str, Any]] = {}

    def load(
        self,
        en_data: dict[str, str],
        zh_data: dict[str, str],
        alignment: AlignmentDict,
    ) -> None:
        """加载数据。"""
        self.en_data = en_data
        self.zh_data = zh_data
        self.matched_entries = alignment.get("matched_entries", [])

    # ── 术语提取 ──────────────────────────────────────────

    def extract(self, min_freq: int = 2, max_ngram: int = 3) -> dict[str, Any]:
        self.extracted = extract_terms(self.en_data, min_freq, max_ngram)
        return self.extracted

    # ── 归并（2 步：分桶 → inflection 归并）──

    def merge_lemmas(self) -> dict[str, dict[str, Any]]:
        if not self.extracted:
            self.extract()

        # Step 1: 原始分桶
        self.merged = raw_merge(self.extracted)
        info(f"  [术语归并] 原始分桶: {len(self.merged)} 个")

        # Step 2: inflection 名词单数归一化归并
        self.merged = inflection_merge(self.merged)
        info(f"  [术语归并] inflection 归并后: {len(self.merged)} 个")

        return self.merged

    # ── 构建术语表 ────────────────────────────────────────

    # ── 术语翻译 + 一致性检查 ─────────────────────────────

    def build_glossary(self, min_freq: int | None = None, min_consensus: float | None = None) -> list[GlossaryDict]:
        """
        纯程序化构建术语表：从 matched_entries 中统计每组术语的已有中文译文。
        """
        if not self.merged:
            self.merge_lemmas()

        min_freq = min_freq if min_freq is not None else cfg.get("term_min_freq", 5)
        min_consensus = min_consensus if min_consensus is not None else cfg.get("term_min_consensus", 0.6)
        assert isinstance(min_freq, int)
        assert isinstance(min_consensus, (int, float))
        max_zh_len = cfg.get("term_max_zh_len", 40)
        max_en_len = cfg.get("term_max_en_len", 60)
        min_total = cfg.get("term_consensus_min_total", 3)

        glossary = _collect_zh_translations(
            self.merged, self.matched_entries,
            min_freq, min_consensus, min_total, max_zh_len, max_en_len,
        )
        glossary = _dedup_zh_conflicts(glossary, self.merged, self.matched_entries)
        self.glossary = glossary
        info(f"  [术语表] {len(glossary)} 条术语（纯程序提取, freq≥{min_freq}, 共识≥{int(min_consensus*100)}%）")
        return glossary

    # ── 便捷入口 ──────────────────────────────────────────

    def merge_and_build(self) -> list[GlossaryDict]:
        """归并 + 纯程序提取术语表（一步完成）。"""
        self.merge_lemmas()
        return self.build_glossary()
