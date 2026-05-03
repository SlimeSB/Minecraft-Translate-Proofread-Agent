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
from src import config as cfg

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
                    union(ni, nj)

    # 收集 >=2 成员的组
    groups: dict[str, list[str]] = defaultdict(list)
    for n in norms:
        groups[find(n)].append(n)

    return [sorted(g, key=lambda n: -merged[n]["freq"]) for g in groups.values() if len(g) >= 2]


def _build_merge_prompt(clusters: list[list[str]]) -> str:
    """构建 LLM 归并 prompt。"""
    blocks: list[str] = [cfg.MERGE_SYSTEM_PROMPT]
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
# 中文互斥 — 短术语救回逻辑
# ═══════════════════════════════════════════════════════════

def _try_rescue_short_term(
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
    # 同时收集长术语变体命中的 key
    for variant in long_info.get("variants", []) if long_info else []:
        pass  # 变体的 key 已在 long_info["keys"] 中

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
        fuzzy_threshold: float | None = None,
    ) -> dict[str, dict[str, Any]]:
        if not self.extracted:
            self.extract()
        fuzzy_threshold = fuzzy_threshold if fuzzy_threshold is not None else cfg.get("fuzzy_cluster_threshold", 65.0)

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

    # ── 术语翻译 + 一致性检查 ─────────────────────────────

    def build_glossary(self, min_freq: int | None = None, min_consensus: float | None = None) -> list[dict[str, str]]:
        """
        纯程序化构建术语表：从 matched_entries 中统计每组术语的已有中文译文。

        :param min_freq: 最少出现次数（归并后），默认从配置取 term_min_freq
        :param min_consensus: 最常用译文占比阈值，默认从配置取 term_min_consensus
        """
        if not self.merged:
            self.merge_lemmas()

        min_freq = min_freq if min_freq is not None else cfg.get("term_min_freq", 5)
        min_consensus = min_consensus if min_consensus is not None else cfg.get("term_min_consensus", 0.6)
        max_zh_len = cfg.get("term_max_zh_len", 40)
        max_en_len = cfg.get("term_max_en_len", 60)
        min_total = cfg.get("term_consensus_min_total", 3)

        from src.tools.terminology_extract import STOP_WORDS

        def _is_useful_term(norm: str, info: dict) -> bool:
            if norm.lower() in STOP_WORDS:
                return False
            if len(norm) <= 2 and norm.isalpha():
                return False
            # 排除纯数字/短标识符
            if re.fullmatch(r"[0-9._-]+", norm):
                return False
            return True

        glossary: list[dict[str, str]] = []
        for norm, info in sorted(self.merged.items(), key=lambda x: -x[1]["freq"]):
            if info["freq"] < min_freq or not _is_useful_term(norm, info):
                continue

            zh_counter: Counter = Counter()
            for k in info["keys"]:
                entry = next((e for e in self.matched_entries if e["key"] == k), None)
                if not entry:
                    continue
                # 描述性条目不参与术语表（desc/lore/flavor/text/message 等）
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
            if total >= min_total and best_count / total >= min_consensus:
                variants = sorted(info["variants"], key=len)
                en_term = variants[0] if variants else norm
                glossary.append({"en": en_term, "zh": best_zh})

        # 中文互斥：同一中文对应多个英文术语时，若短 en 是长 en 的子串，
        # 需要给短术语一次「剔除长术语所在 key 后重新统计」的机会。
        # 若重新统计后短术语指向不同中文，则两者保留；否则删除短的。
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
                        # 短 en 是长 en 的子串 → 给短术语第二次机会
                        rescued = _try_rescue_short_term(item_b, item_a, self.merged, self.matched_entries)
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
            print(msg)

        self.glossary = glossary
        print(f"  [术语表] {len(glossary)} 条术语（纯程序提取, freq≥{min_freq}, 共识≥{int(min_consensus*100)}%）")
        return glossary

    def check_consistency(self) -> list[dict[str, Any]]:
        """
        用术语表检查 matched_entries 中的翻译一致性。
        按词边界匹配（避免子串误匹配：eat 不匹配 Defeat）。
        """
        if not self.glossary:
            return []

        import re

        # 构建术语→标准译文 + regex 模式
        term_info: list[tuple[str, str, re.Pattern]] = []
        for g in self.glossary:
            en_lower = g["en"].lower()
            # 从 merged 找回变体，构建 OR 模式
            variants = [g["en"]]
            if en_lower in self.merged:
                variants = sorted(self.merged[en_lower]["variants"], key=len)
            # 对每个变体用 \b 词边界
            patterns = [re.escape(v.lower()) for v in variants]
            combined = r"\b(?:" + "|".join(patterns) + r")\b"
            term_info.append((g["en"], g["zh"], re.compile(combined, re.IGNORECASE)))

        verdicts: list[dict[str, Any]] = []
        for entry in self.matched_entries:
            key = entry["key"]
            en = entry.get("en", "")
            zh = entry.get("zh", "")
            if not isinstance(en, str) or not isinstance(zh, str) or not zh.strip():
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
                    "reason": f'术语不一致——"{en_term}"在术语表中译为"{std_zh}"，此处未使用',
                    "source": "terminology_check",
                })

        return verdicts

    # ── 便捷入口 ──────────────────────────────────────────

    def merge_and_build(self) -> list[dict[str, str]]:
        """归并 + 纯程序提取术语表（一步完成）。"""
        self.merge_lemmas()
        return self.build_glossary()


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
    glossary = tb.merge_and_build()

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

    result = {
        "glossary_size": len(glossary),
        "terminology_verdicts": verdicts,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

