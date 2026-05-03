"""术语构建与匹配器：从 en_us.json 提取术语、词形归并、构建术语表、
检查翻译一致性。

归并策略: 规则粗筛 → 模糊搜索聚类 → LLM 裁决同形异体

用法（独立）:
    python terminology_builder.py --en en_us.json --zh zh_cn.json \
        --alignment alignment.json [--output glossary.json] [--verdicts term_verdicts.json]

用法（模块）:
    from terminology_builder import TerminologyBuilder
    tb = TerminologyBuilder()
    tb.load(en_data, zh_data, alignment)
    glossary = tb.merge_and_build(llm_call=my_llm_fn, min_freq=3)
    verdicts = tb.check_consistency()
"""
import argparse
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path
from typing import Any, Callable

from src.tools.terminology_extract import extract_terms, tokenize
from src.tools.fuzzy_search import calc_similarity

# ═══════════════════════════════════════════════════════════
# 持久化词形缓存（持续学习）
# ═══════════════════════════════════════════════════════════

DEFAULT_CACHE_PATH = "lemma_cache.json"


class LemmaCache:
    """持久化词形映射缓存。每次 LLM 裁决后写入，下次直接复用。"""

    def __init__(self, path: str = DEFAULT_CACHE_PATH):
        self.path = Path(path)
        self.map: dict[str, dict[str, Any]] = {}   # {variant: {canonical, freq, source}}
        self._loaded = False

    def load(self) -> dict[str, dict[str, Any]]:
        if self._loaded:
            return self.map
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.map = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.map = {}
        self._loaded = True
        return self.map

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.map, f, ensure_ascii=False, indent=2)

    def lookup(self, term: str) -> str | None:
        """查缓存：已知 variant 返回 canonical，否则 None。"""
        key = term.lower().strip()
        entry = self.map.get(key)
        if entry:
            entry["freq"] = entry.get("freq", 0) + 1
            return entry.get("canonical", key)
        return None

    def record(self, canonical: str, members: list[str], source: str = "llm") -> None:
        """写入一批映射并保存。"""
        canon_key = canonical.lower().strip()
        # 确保 canonical 自身在缓存中
        if canon_key not in self.map:
            self.map[canon_key] = {"canonical": canonical, "freq": 0, "source": source}
        self.map[canon_key]["freq"] = self.map[canon_key].get("freq", 0) + 1

        for m in members:
            mk = m.lower().strip()
            if mk == canon_key:
                continue
            if mk in self.map:
                self.map[mk]["freq"] = self.map[mk].get("freq", 0) + 1
            else:
                self.map[mk] = {"canonical": canon_key, "freq": 1, "source": source}
        self.save()

    def stats(self) -> dict[str, int]:
        return {"entries": len(self.map), "path": str(self.path)}


# ═══════════════════════════════════════════════════════════
# 第一遍：按原始形式分桶（不做词形归并——归并交给缓存+LLM）
# ═══════════════════════════════════════════════════════════

def _raw_merge(extracted: dict[str, Any]) -> dict[str, dict[str, Any]]:
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
            merged[norm]["keys"] = merged[norm]["keys"][:20]
    return merged


def _apply_cache_merge(
    merged: dict[str, dict[str, Any]],
    cache: LemmaCache,
) -> tuple[dict[str, dict[str, Any]], int]:
    """
    用缓存中的已知映射归并 merged 桶。
    返回 (归并后的 merged, 命中次数)。
    """
    hits = 0
    # 收集缓存映射: {raw_key → canonical_key}
    redirect: dict[str, str] = {}
    for raw_key in merged:
        canon = cache.lookup(raw_key)
        if canon and canon != raw_key:
            redirect[raw_key] = canon
            hits += 1
            # bump canonical freq so it stays "hot"
            cache.lookup(canon)

    if not redirect:
        return merged, 0

    new_merged: dict[str, dict[str, Any]] = {}
    for raw_key, info in merged.items():
        target = redirect.get(raw_key, raw_key)
        if target not in new_merged:
            if target in merged:
                new_merged[target] = {
                    "normalized": merged[target]["normalized"],
                    "variants": set(merged[target]["variants"]),
                    "freq": merged[target]["freq"],
                    "keys": list(merged[target]["keys"]),
                    "ngram_type": merged[target]["ngram_type"],
                }
            else:
                new_merged[target] = {
                    "normalized": target,
                    "variants": set(),
                    "freq": 0,
                    "keys": [],
                    "ngram_type": info["ngram_type"],
                }
        new_merged[target]["variants"] |= info["variants"]
        new_merged[target]["freq"] += info["freq"]
        for k in info["keys"]:
            if k not in new_merged[target]["keys"]:
                new_merged[target]["keys"].append(k)
        new_merged[target]["keys"] = new_merged[target]["keys"][:20]

    return new_merged, hits


# ═══════════════════════════════════════════════════════════
# 模糊聚类 + LLM 裁决
# ═══════════════════════════════════════════════════════════

def _fuzzy_cluster(
    merged: dict[str, dict[str, Any]],
    threshold: float = 65.0,
) -> list[list[str]]:
    """
    在已规则归并的桶之间做模糊聚类。
    返回: [[norm_a, norm_b, ...], ...] 候选合并组
    """
    norms = sorted(merged.keys(), key=lambda n: -merged[n]["freq"])
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
    top_n = min(len(norms), 200)
    for i in range(top_n):
        for j in range(i + 1, top_n):
            ni, nj = norms[i], norms[j]
            sim = calc_similarity(ni, nj)
            if sim >= threshold:
                # 额外条件：至少共享一个 token 或长度比例为 0.5~2
                ti, tj = set(ni.split()), set(nj.split())
                len_ratio = min(len(ni), len(nj)) / max(len(ni), len(nj), 1)
                if ti & tj or len_ratio > 0.4:
                    union(ni, nj)

    # 收集 >=2 成员的组
    groups: dict[str, list[str]] = defaultdict(list)
    for n in norms:
        groups[find(n)].append(n)

    return [sorted(g, key=lambda n: -merged[n]["freq"]) for g in groups.values() if len(g) >= 2]


def _build_merge_prompt(clusters: list[list[str]]) -> str:
    """构建 LLM 归并 prompt。"""
    blocks: list[str] = [
        "你是英文术语规范化专家。以下每组是规则归并后仍疑似同源的术语候选群。",
        "判断组内哪些术语确实应合并为同一词条（同一概念的不同拼写/词形），哪些应保留为独立术语。",
        "输出 JSON 数组，每个元素: { \"canonical\": \"规范形式\", \"members\": [\"成员1\", ...] }",
        "不合并的单独术语不需要输出。只输出 JSON 数组，不要其他文字。\n",
    ]
    for i, group in enumerate(clusters):
        lines = [f"## 候选组 {i+1}"]
        for term in group:
            lines.append(f"  - {term}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _parse_merge_response(response: str) -> dict[str, str]:
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


def _apply_llm_merge(
    merged: dict[str, dict[str, Any]],
    llm_mapping: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """根据 LLM 裁决将 merged 桶合并。"""
    new_merged: dict[str, dict[str, Any]] = {}
    for norm, info in merged.items():
        target = llm_mapping.get(norm, norm)
        if target not in new_merged:
            new_merged[target] = {
                "normalized": target,
                "variants": set(),
                "freq": 0,
                "keys": [],
                "ngram_type": info["ngram_type"],
            }
        new_merged[target]["variants"] |= info["variants"]
        new_merged[target]["freq"] += info["freq"]
        for k in info["keys"]:
            if k not in new_merged[target]["keys"]:
                new_merged[target]["keys"].append(k)
        new_merged[target]["keys"] = new_merged[target]["keys"][:20]
    return new_merged


# ═══════════════════════════════════════════════════════════
# 术语表构建器
# ═══════════════════════════════════════════════════════════

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
        fuzzy_threshold: float = 65.0,
    ) -> dict[str, dict[str, Any]]:
        if not self.extracted:
            self.extract()

        self.cache.load()

        # Step 1: 原始分桶
        self.merged = _raw_merge(self.extracted)
        print(f"  [术语归并] 原始分桶: {len(self.merged)} 个")

        # Step 2: 缓存查表
        if self.cache.map:
            self.merged, self._cache_hits = _apply_cache_merge(self.merged, self.cache)
            print(f"  [术语归并] 缓存命中: {self._cache_hits} 条, 归并后: {len(self.merged)} 个")

        if llm_call is None or not self.merged:
            return self.merged

        # Step 3: 模糊聚类（在缓存归并后的桶之间）
        clusters = _fuzzy_cluster(self.merged, threshold=fuzzy_threshold)
        if not clusters:
            return self.merged

        print(f"  [术语归并] 模糊聚类候选组: {len(clusters)} 组, 共 {sum(len(c) for c in clusters)} 个术语")

        # Step 4: LLM 裁决 + 写回缓存
        prompt = _build_merge_prompt(clusters)
        try:
            response = llm_call(prompt)
            mapping = _parse_merge_response(response)
            if mapping:
                # 记录到缓存（canonical → members 方向）
                canon_map: dict[str, list[str]] = {}
                for member, canon in mapping.items():
                    canon_map.setdefault(canon, []).append(member)
                for canon, members in canon_map.items():
                    self.cache.record(canon, members, source="llm")

                self.merged = _apply_llm_merge(self.merged, mapping)
                print(f"  [术语归并] LLM 合并完成: 缓存 {len(self.cache.map)} 条, 归并后 {len(self.merged)} 个桶")
        except Exception:
            pass

        return self.merged

    # ── 构建术语表 ────────────────────────────────────────

    def build_glossary(self, min_freq: int = 3) -> list[dict[str, Any]]:
        """对归并后的术语统计翻译，构建术语表。"""
        if not self.merged:
            self.merge_lemmas()

        glossary: list[dict[str, Any]] = []
        for norm, info in sorted(self.merged.items(), key=lambda x: -x[1]["freq"]):
            if info["freq"] < min_freq:
                continue
            variants = sorted(info["variants"], key=len)
            translations: Counter = Counter()
            translation_samples: dict[str, list[str]] = defaultdict(list)
            for k in info["keys"]:
                zh_val = self.zh_data.get(k, "")
                if zh_val:
                    translations[zh_val] += 1
                    translation_samples[zh_val].append(k)
            if not translations:
                continue

            most_common_zh, _ = translations.most_common(1)[0]
            all_translations = [
                {"translation": zh, "count": c, "sample_keys": translation_samples[zh][:3]}
                for zh, c in translations.most_common(5)
            ]

            glossary.append({
                "en_term": variants[0],
                "en_variants": variants,
                "normalized": norm,
                "freq": info["freq"],
                "most_common_translation": most_common_zh,
                "all_translations": all_translations,
                "is_consistent": len(all_translations) == 1,
            })

        self.glossary = glossary
        return glossary

    # ── 一致性检查 ────────────────────────────────────────

    def check_consistency(self) -> list[dict[str, Any]]:
        """检查 matched_entries 中术语翻译是否与术语表一致。"""
        if not self.glossary:
            self.build_glossary()

        term_map: dict[str, str] = {}
        for g in self.glossary:
            if g["is_consistent"]:
                for variant in g["en_variants"]:
                    term_map[variant.lower()] = g["most_common_translation"]

        verdicts: list[dict[str, Any]] = []
        for entry in self.matched_entries:
            key = entry["key"]
            en = entry["en"]
            zh = entry["zh"]
            if not isinstance(en, str) or not isinstance(zh, str):
                continue

            en_lower = en.lower()
            checked: set[str] = set()
            for term, standard_zh in term_map.items():
                if term in checked:
                    continue
                if term.lower() in en_lower:
                    checked.add(term)
                    if standard_zh not in zh:
                        verdicts.append({
                            "key": key,
                            "en_current": en,
                            "zh_current": zh,
                            "verdict": "❌ FAIL",
                            "suggestion": standard_zh,
                            "reason": f'术语不一致，"\\"{term}\\"应译为"\\"{standard_zh}\\""',
                            "source": "terminology_check",
                        })
        return verdicts

    def get_inconsistent_terms(self) -> list[dict[str, Any]]:
        if not self.glossary:
            self.build_glossary()
        return [
            {
                "en_term": g["en_term"],
                "normalized": g["normalized"],
                "freq": g["freq"],
                "translations": [f'{t["translation"]}({t["count"]})' for t in g["all_translations"]],
            }
            for g in self.glossary
            if not g["is_consistent"]
        ]

    # ── 便捷入口 ──────────────────────────────────────────

    def merge_and_build(
        self,
        llm_call: Callable[[str], str] | None = None,
        min_freq: int = 3,
        fuzzy_threshold: float = 65.0,
    ) -> list[dict[str, Any]]:
        """归并 + 构建术语表（一步完成）。"""
        self.merge_lemmas(llm_call=llm_call, fuzzy_threshold=fuzzy_threshold)
        return self.build_glossary(min_freq=min_freq)


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="从语言文件提取术语、构建术语表、检查一致性")
    parser.add_argument("--en", required=True, help="en_us.json 路径")
    parser.add_argument("--zh", required=True, help="zh_cn.json 路径")
    parser.add_argument("--alignment", required=True, help="alignment.json 路径")
    parser.add_argument("--min-freq", type=int, default=3, help="术语最低频次阈值（归并后），默认3")
    parser.add_argument("--cache-path", default=DEFAULT_CACHE_PATH,
                        help=f"词形缓存路径，默认 {DEFAULT_CACHE_PATH}")
    parser.add_argument("--output-glossary", default=None, help="保存术语表到文件")
    parser.add_argument("--output-verdicts", default=None, help="保存术语一致性 verdicts 到文件")

    args = parser.parse_args()

    try:
        with open(args.en, "r", encoding="utf-8") as f:
            en_data = json.load(f)
        with open(args.zh, "r", encoding="utf-8") as f:
            zh_data = json.load(f)
        with open(args.alignment, "r", encoding="utf-8") as f:
            alignment = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    tb = TerminologyBuilder(cache_path=args.cache_path)
    tb.load(en_data, zh_data, alignment)
    tb.extract(min_freq=2, max_ngram=3)
    glossary = tb.merge_and_build(llm_call=None, min_freq=args.min_freq)

    if args.output_glossary:
        p = Path(args.output_glossary)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(glossary, f, ensure_ascii=False, indent=2)

    verdicts = tb.check_consistency()
    if args.output_verdicts:
        p = Path(args.output_verdicts)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(verdicts, f, ensure_ascii=False, indent=2)

    inconsistent = tb.get_inconsistent_terms()
    result = {
        "glossary_size": len(glossary),
        "consistent_terms": sum(1 for g in glossary if g["is_consistent"]),
        "inconsistent_terms": inconsistent,
        "terminology_verdicts": verdicts,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

