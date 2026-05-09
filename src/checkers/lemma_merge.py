"""
词形归并与中文互斥处理。

归并策略: 规则粗筛 → 缓存查表 → 模糊搜索聚类 → LLM 裁决同形异体
"""
import json
import re
from collections import defaultdict, Counter
from typing import Any

from src.tools.fuzzy_search import calc_similarity
from src import config as cfg
from .lemma_cache import LemmaCache

_MAX_KEYS_PER_TERM = cfg.get("max_keys_per_term", 20)


# ═══════════════════════════════════════════════════════════
# 第一遍：按原始形式分桶（不做词形归并——归并交给缓存+LLM）
# ═══════════════════════════════════════════════════════════

def raw_merge(extracted: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """将 n-gram 提取结果按原始词面分桶。"""
    merged: dict[str, dict[str, Any]] = {}
    for ngram_type in ("unigrams", "bigrams", "trigrams"):
        for item in extracted.get(ngram_type, []):
            term = item["term"]
            norm = term.lower().strip()
            if norm not in merged:
                merged[norm] = {
                    "normalized": term,  # 保留原始形式
                    "variants": set(),
                    "freq": 0,
                    "keys": [],
                    "ngram_type": ngram_type,
                }
            merged[norm]["variants"].add(term)
            merged[norm]["freq"] += item["freq"]
            for k in item["keys"]:
                if k not in merged[norm]["keys"]:
                    merged[norm]["keys"].append(k)
            merged[norm]["keys"] = merged[norm]["keys"][:_MAX_KEYS_PER_TERM]
    return merged


# ═══════════════════════════════════════════════════════════
# 归并守卫：阻止多词短语被吞入单词
# ═══════════════════════════════════════════════════════════

def _is_token_proper_subset(a: str, b: str) -> bool:
    """判断一个术语的 token 集合是否是另一个的真子集（如 "upgrade adds" ⊃ "upgrade"）。"""
    ta = set(a.split())
    tb = set(b.split())
    return ta < tb or tb < ta


def _apply_merge_map(
    merged: dict[str, dict[str, Any]],
    redirect: dict[str, str],
    guard_token_subset: bool = True,
) -> dict[str, dict[str, Any]]:
    """根据 redirect 字典合并 merged 桶。返回新的 merged dict。"""
    new_merged: dict[str, dict[str, Any]] = {}
    for norm, info in merged.items():
        target = redirect.get(norm, norm)
        if guard_token_subset and target != norm and _is_token_proper_subset(norm, target):
            target = norm
        if target not in new_merged:
            new_merged[target] = {
                "normalized": target,
                "variants": set(),
                "freq": 0,
                "keys": [],
                "ngram_type": info["ngram_type"],
            }
        new_merged[target]["variants"] |= info["variants"]
        for k in info["keys"]:
            if k not in new_merged[target]["keys"]:
                new_merged[target]["keys"].append(k)
        new_merged[target]["keys"] = new_merged[target]["keys"][:_MAX_KEYS_PER_TERM]
    for info in new_merged.values():
        info["freq"] = len(info["keys"])
    return new_merged


def apply_cache_merge(
    merged: dict[str, dict[str, Any]],
    cache: LemmaCache,
) -> tuple[dict[str, dict[str, Any]], int]:
    """
    用缓存中的已知映射归并 merged 桶。
    返回 (归并后的 merged, 命中次数)。
    """
    hits = 0
    redirect: dict[str, str] = {}
    for raw_key in merged:
        canon = cache.lookup(raw_key)
        if canon and canon != raw_key and not _is_token_proper_subset(raw_key, canon):
            redirect[raw_key] = canon
            hits += 1
            cache.lookup(canon)  # bump canonical freq so it stays "hot"

    if not redirect:
        return merged, 0

    return _apply_merge_map(merged, redirect, guard_token_subset=False), hits


# ═══════════════════════════════════════════════════════════
# 模糊聚类 + LLM 裁决
# ═══════════════════════════════════════════════════════════

def fuzzy_cluster(
    merged: dict[str, dict[str, Any]],
    threshold: float = 65.0,
) -> list[list[str]]:
    """
    在已规则归并的桶之间做模糊聚类。
    返回: [[norm_a, norm_b, ...], ...] 候选合并组
    """
    norms = sorted(merged.keys(), key=lambda n: -len(merged[n]["keys"]))
    parents = {n: n for n in norms}

    def find(n: str) -> str:
        while parents[n] != n:
            parents[n] = parents[parents[n]]
            n = parents[n]
        return n

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parents[ra] = rb

    # 两两比对（限制高频词范围以避免 O(n²) 爆炸）
    top_n = min(len(norms), cfg.get("fuzzy_cluster_top_n", 200))
    for i in range(top_n):
        for j in range(i + 1, top_n):
            ni, nj = norms[i], norms[j]
            sim = calc_similarity(ni, nj)
            if sim >= threshold:
                # 额外条件：至少共享一个 token 或长度比例为 0.5~2
                ti, tj = set(ni.split()), set(nj.split())
                len_ratio = min(len(ni), len(nj)) / max(len(ni), len(nj), 1)
                if ti & tj or len_ratio > 0.4:
                    # 阻止单词语吞噬多词术语
                    if ti < tj or tj < ti:
                        continue
                    union(ni, nj)

    # 收集 >=2 成员的组
    groups: dict[str, list[str]] = defaultdict(list)
    for n in norms:
        groups[find(n)].append(n)

    return [sorted(g, key=lambda n: -merged[n]["freq"]) for g in groups.values() if len(g) >= 2]


def build_merge_prompt(clusters: list[list[str]]) -> str:
    """构建 LLM 归并 prompt。"""
    blocks: list[str] = [cfg.MERGE_SYSTEM_PROMPT]
    for i, group in enumerate(clusters):
        lines = [f"## 候选组 {i+1}"]
        for term in group:
            lines.append(f"  - {term}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def parse_merge_response(response: str) -> dict[str, str]:
    """解析 LLM 归并响应: {member: canonical, ...}"""
    mapping: dict[str, str] = {}
    try:
        data = json.loads(response)
        if isinstance(data, list):
            for item in data:
                canon = item.get("canonical", "")
                members = item.get("members", [])
                if canon and members:
                    for m in members:
                        mapping[m] = canon
                    if canon not in mapping:
                        mapping[canon] = canon
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", response, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                for item in data:
                    canon = item.get("canonical", "")
                    members = item.get("members", [])
                    if canon and members:
                        for mb in members:
                            mapping[mb] = canon
                        if canon not in mapping:
                            mapping[canon] = canon
            except json.JSONDecodeError:
                pass
    return mapping


def apply_llm_merge(
    merged: dict[str, dict[str, Any]],
    llm_mapping: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """根据 LLM 裁决将 merged 桶合并。过滤多词→单词的非法映射。"""
    return _apply_merge_map(merged, llm_mapping, guard_token_subset=True)


# ═══════════════════════════════════════════════════════════
# 中文互斥 — 短术语救回逻辑
# ═══════════════════════════════════════════════════════════

def try_rescue_short_term(
    short_item: dict[str, str],
    long_item: dict[str, str],
    merged: dict[str, dict[str, Any]],
    matched_entries: list[dict[str, str]],
) -> dict[str, str] | None:
    """
    短 en 是长 en 的子串且中文冲突时，剔除长术语所在的 key 后重新统计。
    若短术语在剩余 key 中指向不同中文且满足共识阈值，返回新术语条目；否则返回 None。
    """
    en_short = short_item["en"].lower()
    en_long = long_item["en"].lower()
    zh_long = long_item["zh"]

    # 找到短术语的 merged 信息（内层 key 为归一化形式）
    short_info = merged.get(en_short) or merged.get(en_short.replace(" ", "_"))
    long_info = merged.get(en_long) or merged.get(en_long.replace(" ", "_"))
    if not short_info:
        return None

    # 收集长术语命中的所有 key
    long_keys: set[str] = set()
    if long_info:
        long_keys.update(long_info.get("keys", []))

    # 收集短术语独有的 key（剔除长术语命中的 key）
    short_only_keys = [k for k in short_info.get("keys", []) if k not in long_keys]
    if not short_only_keys:
        return None

    max_zh_len = cfg.get("term_max_zh_len", 40)
    max_en_len = cfg.get("term_max_en_len", 60)
    min_total = cfg.get("term_consensus_min_total", 3)
    min_consensus = cfg.get("term_min_consensus", 0.6)

    zh_counter: Counter = Counter()
    for k in short_only_keys:
        entry = next((e for e in matched_entries if e["key"] == k), None)
        if not entry:
            continue
        if any(p in k for p in cfg.DESC_KEY_SUFFIXES):
            continue
        zh_val = entry.get("zh", "").strip()
        en_val = entry.get("en", "")
        if not zh_val or zh_val == en_val or len(zh_val) > max_zh_len or len(en_val) > max_en_len:
            continue
        # 确认短术语的变体确实在 en_val 中出现
        variants = short_info.get("variants", {en_short})
        if not any(re.search(r"\b" + re.escape(v) + r"\b", en_val, re.IGNORECASE) for v in variants):
            continue
        zh_counter[zh_val[:120]] += 1

    if not zh_counter:
        return None

    best_zh, best_count = zh_counter.most_common(1)[0]
    total = sum(zh_counter.values())
    if total < min_total or best_count / total < min_consensus:
        return None

    # 重新统计后的中文与长术语中文不同 → 救回
    if best_zh != zh_long:
        return {"en": short_item["en"], "zh": best_zh}

    return None
