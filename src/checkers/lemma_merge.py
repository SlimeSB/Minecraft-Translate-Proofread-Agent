"""
词形归并与中文互斥处理。

归并策略: 规则分桶 → inflection 名词单数归一化归并
"""
import json
import re
from collections import defaultdict, Counter
from typing import Any

import inflection

from src.logging import debug
from src import config as cfg

_MAX_KEYS_PER_TERM = cfg.get("max_keys_per_term", 20)


# ═══════════════════════════════════════════════════════════
# 第一遍：按原始形式分桶（不做词形归并——归并交给 inflection）
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
            debug(f"  [归并守卫] 阻止: \"{norm}\" 并入 \"{target}\" (token 真子集)")
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


# ═══════════════════════════════════════════════════════════
# Inflection 名词单数归一化归并
# ═══════════════════════════════════════════════════════════

def inflection_lemmatize_term(term: str) -> str:
    """对 N-gram 术语的每个词做名词单数归一化后重组。"""
    return " ".join(inflection.singularize(w.lower()) for w in term.split())


def inflection_merge(
    merged: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """按 inflection 归一化形式合并 merged 桶。"""
    lemma_map: dict[str, list[str]] = defaultdict(list)
    for norm in merged:
        lemma = inflection_lemmatize_term(norm)
        lemma_map[lemma].append(norm)

    redirect: dict[str, str] = {}
    for lemma, terms in lemma_map.items():
        if len(terms) < 2:
            continue
        if lemma in merged:
            for t in terms:
                if t != lemma:
                    redirect[t] = lemma
                    debug(f"  [术语归并] \"{t}\" → \"{lemma}\" (inflection)")
        else:
            best = max(terms, key=lambda t: len(merged[t]["keys"]))
            for t in terms:
                if t != best:
                    redirect[t] = best
                    debug(f"  [术语归并] \"{t}\" → \"{best}\" (inflection, max keys)")

    if not redirect:
        return merged

    return _apply_merge_map(merged, redirect, guard_token_subset=True)


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
