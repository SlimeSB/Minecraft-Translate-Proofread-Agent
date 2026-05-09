"""术语构建与匹配器：从 en_us.json 提取术语、词形归并、构建术语表、
检查翻译一致性。

归并策略: 规则粗筛 → 模糊搜索聚类 → LLM 裁决同形异体

用法:
    from terminology_builder import TerminologyBuilder, llm_verify_glossary, check_consistency
    tb = TerminologyBuilder()
    tb.load(en_data, zh_data, alignment)
    glossary = tb.merge_and_build(llm_call=my_llm_fn)
    glossary = llm_verify_glossary(glossary, tb.en_data, my_llm_fn)
    verdicts = check_consistency(glossary, tb.matched_entries, tb.merged)
"""
import json
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any, Callable

from src.logging import info, warn
from src.tools.terminology_extract import extract_terms
from src import config as cfg
from .lemma_cache import LemmaCache, DEFAULT_CACHE_PATH
from .lemma_merge import (
    raw_merge,
    apply_cache_merge,
    fuzzy_cluster,
    build_merge_prompt,
    parse_merge_response,
    apply_llm_merge,
    try_rescue_short_term,
)


# ═══════════════════════════════════════════════════════════
# 公共中文提取
# ═══════════════════════════════════════════════════════════

def _extract_common_zh(zh_counter: Counter, min_ratio: float) -> str | None:
    """从多个中文译文中提取公共子串，忽略离群值。

    遍历每种译文，若它作为**真子串**出现在 ≥ min_ratio 比例的**其他**译文中，
    则为公共项。自身匹配不计入。
    返回最长的公共项，无则返回 None。

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
    return best if best else None


# ═══════════════════════════════════════════════════════════
# 术语表构建器
# ═══════════════════════════════════════════════════════════

def _parse_glossary_corrections(response: str) -> dict[str, dict[str, str]]:
    """解析 LLM 返回的术语修正 JSON 数组。"""
    import json
    import re
    jt = response.strip()
    if "```" in jt:
        m = re.search(r"```(?:json)?\\s*\\n?(.*?)```", jt, re.DOTALL)
        if m:
            jt = m.group(1).strip()
    try:
        arr = json.loads(jt)
    except json.JSONDecodeError as e:
        from src.logging import warn; warn(f"[TerminologyBuilder] LLM 响应 JSON 解析失败: {e}")
        arr = []
    if not isinstance(arr, list):
        return {}
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


def _is_useful_term(norm: str) -> bool:
    """筛选有用的术语：过滤停用词、过短、含数字、纯符号。"""
    from src.tools.terminology_extract import STOP_WORDS
    stop_lower = {w.lower() for w in STOP_WORDS}
    norm_lower = norm.lower()
    if norm_lower in stop_lower:
        return False
    if len(norm) <= 2:
        return False
    if re.search(r"\d", norm):
        return False
    if re.fullmatch(r"[0-9._-]+", norm):
        return False
    for word in norm_lower.split():
        if word in stop_lower:
            return False
    return True


def _collect_zh_translations(
    merged: dict[str, dict[str, Any]],
    matched_entries: list[dict[str, str]],
    min_freq: int,
    min_consensus: float,
    min_total: int,
    max_zh_len: int,
    max_en_len: int,
) -> list[dict[str, str]]:
    """从 matched_entries 统计每组术语的中文译文，构建初始术语表。"""
    glossary: list[dict[str, str]] = []
    for norm, info in sorted(merged.items(), key=lambda x: -len(x[1]["keys"])):
        if len(info["keys"]) < min_freq or not _is_useful_term(norm):
            continue

        zh_counter: Counter = Counter()
        for k in info["keys"]:
            entry = next((e for e in matched_entries if e["key"] == k), None)
            if not entry:
                continue
            if any(p in k for p in cfg.DESC_KEY_SUFFIXES):
                continue
            zh_val = entry.get("zh", "").strip()
            en_val = entry.get("en", "")
            if not zh_val or zh_val == en_val or len(zh_val) > max_zh_len or len(en_val) > max_en_len:
                continue
            variants = info["variants"]
            if not any(re.search(r"\b" + re.escape(v) + r"\b", en_val, re.IGNORECASE) for v in variants):
                continue
            zh_counter[zh_val[:120]] += 1

        if not zh_counter:
            continue

        best_zh, best_count = zh_counter.most_common(1)[0]
        total = sum(zh_counter.values())
        variants = sorted(info["variants"], key=len)
        en_term = variants[0] if variants else norm
        if total >= min_total and best_count / total >= min_consensus:
            glossary.append({"en": en_term, "zh": best_zh})
        elif total >= min_total:
            common = _extract_common_zh(zh_counter, min_consensus)
            if common:
                glossary.append({"en": en_term, "zh": common})

    return glossary


def _dedup_zh_conflicts(
    glossary: list[dict[str, str]],
    merged: dict[str, dict[str, Any]],
    matched_entries: list[dict[str, str]],
) -> list[dict[str, str]]:
    """中文互斥去重：同一中文对应多个英文术语时，给短术语第二次机会。"""
    before_dedup = len(glossary)
    zh_to_entries: dict[str, list[dict[str, str]]] = {}
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
        to_remove: list[dict[str, str]] = []
        for i, item_a in enumerate(sorted_items):
            en_a_l = item_a["en"].lower()
            for j in range(i + 1, len(sorted_items)):
                item_b = sorted_items[j]
                en_b_l = item_b["en"].lower()
                if en_b_l in en_a_l and item_b not in to_remove:
                    rescued = try_rescue_short_term(item_b, item_a, merged, matched_entries)
                    if rescued:
                        glossary.append(rescued)
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
    glossary: Sequence[dict[str, Any]],
    en_data: dict[str, str],
    llm_call: Callable[[str], str] | None,
) -> list[dict[str, Any]]:
    """LLM 校验术语表: 每条术语取 1 最长 + 4 最短含术语原文, 交 LLM 复核。

    Args:
        glossary: 术语表列表，每项含 "en" 和 "zh" 键
        en_data: 英文条目数据 (key -> en text)
        llm_call: LLM 调用函数

    Returns:
        修正后的术语表（与传入的 glossary 为同一列表对象）
    """
    if not glossary or not llm_call:
        return glossary

    import re
    term_sources: dict[str, list[str]] = {}
    for g in glossary:
        en_lower = g["en"].lower()
        term_sources[en_lower] = []
        for en_val in en_data.values():
            if not isinstance(en_val, str):
                continue
            if re.search(r"\b" + re.escape(en_lower) + r"\b", en_val, re.IGNORECASE):
                term_sources[en_lower].append(en_val)

    lines: list[str] = []
    verify_items: list[dict[str, Any]] = []
    for g in glossary:
        en_lower = g["en"].lower()
        sources = term_sources.get(en_lower, [])
        if not sources:
            continue
        unique = list(dict.fromkeys(sources))
        if len(unique) < 2:
            continue
        sorted_len = sorted(unique, key=len)
        ctx = [sorted_len[-1]] + sorted_len[:4]
        block = 'Term: "' + g["en"] + '" -> "' + g["zh"] + '"\n'
        for j, txt in enumerate(ctx):
            block += '  [' + str(j + 1) + '] "' + txt + '"\n'
        lines.append(block)
        verify_items.append(g)

    if not verify_items:
        return glossary

    prompt = (
        '你是Minecraft模组翻译术语专家。请校验以下自动提取的术语表。\n'
        '自动术语表从多个模组统计提取，可能存在错误。\n'
        '判断每条术语译文是否合适，不合适给出修正。\n'
        '输出JSON: [{"en":"原文","old_zh":"原中文","new_zh":"修正或原中文","reason":"理由"}]\n'
        '仅输出需要修正的。仅输出JSON数组。\n\n'
        + "\n\n".join(lines)
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
    glossary: Sequence[dict[str, Any]],
    matched_entries: Sequence[dict[str, Any]],
    merged: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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

    verdicts: list[dict[str, Any]] = []
    for entry in matched_entries:
        key = entry["key"]
        en = entry.get("en", "")
        zh = entry.get("zh", "")
        if not isinstance(en, str) or not isinstance(zh, str) or not zh.strip():
            continue

        if "music_disc" in key and key.endswith(".desc"):
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
                "source": "terminology_check",
            })

    return verdicts


class TerminologyBuilder:
    """术语提取、归并、匹配的完整流水线。"""

    def __init__(self, cache_path: str = DEFAULT_CACHE_PATH):
        self.en_data: dict[str, str] = {}
        self.zh_data: dict[str, str] = {}
        self.matched_entries: list[dict[str, str]] = []
        self.extracted: dict[str, Any] = {}
        self.glossary: list[dict[str, Any]] = []
        self.merged: dict[str, dict[str, Any]] = {}
        self.cache = LemmaCache(cache_path)
        self._cache_hits = 0

    def load(
        self,
        en_data: dict[str, str],
        zh_data: dict[str, str],
        alignment: dict[str, Any],
    ) -> None:
        """加载数据。"""
        self.en_data = en_data
        self.zh_data = zh_data
        self.matched_entries = alignment.get("matched_entries", [])

    # ── 术语提取 ──────────────────────────────────────────

    def extract(self, min_freq: int = 2, max_ngram: int = 3) -> dict[str, Any]:
        self.extracted = extract_terms(self.en_data, min_freq, max_ngram)
        return self.extracted

    # ── 归并（3+1 步：分桶 → 缓存查表 → 模糊聚类 → LLM 裁决 → 写回缓存）──

    def merge_lemmas(
        self,
        llm_call: Callable[[str], str] | None = None,
        fuzzy_threshold: float | None = None,
    ) -> dict[str, dict[str, Any]]:
        if not self.extracted:
            self.extract()
        fuzzy_threshold = fuzzy_threshold if fuzzy_threshold is not None else float(cfg.get("fuzzy_cluster_threshold", 65.0))  # type: ignore[arg-type]

        self.cache.load()

        # Step 1: 原始分桶
        self.merged = raw_merge(self.extracted)
        info(f"  [术语归并] 原始分桶: {len(self.merged)} 个")

        # Step 2: 缓存查表
        if self.cache.map:
            self.merged, self._cache_hits = apply_cache_merge(self.merged, self.cache)
            info(f"  [术语归并] 缓存命中: {self._cache_hits} 条, 归并后: {len(self.merged)} 个")

        # Step 3: 模糊聚类（纯算法，不需要 LLM）
        if not self.merged:
            return self.merged

        clusters = fuzzy_cluster(self.merged, threshold=fuzzy_threshold)
        if not clusters:
            return self.merged

        info(f"  [术语归并] 模糊聚类候选组: {len(clusters)} 组, 共 {sum(len(c) for c in clusters)} 个术语")

        # Step 4: LLM 裁决 + 写回缓存（仅在有 llm_call 时）
        if llm_call is not None:
            prompt = build_merge_prompt(clusters)
            try:
                response = llm_call(prompt)
                mapping = parse_merge_response(response)
                if mapping:
                    canon_map: dict[str, list[str]] = {}
                    for member, canon in mapping.items():
                        canon_map.setdefault(canon, []).append(member)
                    for canon, members in canon_map.items():
                        self.cache.record(canon, members, source="llm")

                    self.merged = apply_llm_merge(self.merged, mapping)
                    info(f"  [术语归并] LLM 合并完成: 缓存 {len(self.cache.map)} 条, 归并后 {len(self.merged)} 个桶")
            except Exception as e:
                warn(f"[术语归并] LLM 归并调用异常: {type(e).__name__}: {e}")

        return self.merged

    # ── 构建术语表 ────────────────────────────────────────

    # ── 术语翻译 + 一致性检查 ─────────────────────────────

    def build_glossary(self, min_freq: int | None = None, min_consensus: float | None = None) -> list[dict[str, str]]:
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

    def merge_and_build(
        self, llm_call: Callable[[str], str] | None = None
    ) -> list[dict[str, str]]:
        """归并 + 纯程序提取术语表（一步完成）。"""
        self.merge_lemmas(llm_call=llm_call)
        return self.build_glossary()


