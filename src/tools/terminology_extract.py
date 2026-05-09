"""
术语提取工具：从 en_us.json 中提取高频词汇和 n-gram 短语候选。
用于 translation-reviewer agent 的 Phase 2。

用法:
    python terminology_extract.py --en path/to/en_us.json --min-freq 2 --max-ngram 3

输出:
    JSON: {
        "unigrams": [{"term": "...", "freq": N, "keys": [...]}, ...],
        "bigrams": [{"term": "...", "freq": N, "keys": [...]}, ...],
        "trigrams": [{"term": "...", "freq": N, "keys": [...]}, ...],
        "stats": {...}
    }
"""
import argparse
import json
import re
import sys
from collections import defaultdict


# ── stop words ────────────────────────────────────────────
from ..config import get as _cfg_get

def _load_blacklist() -> set[str]:
    """从 review_config.json 的 term_blacklist 加载黑名单词。"""
    words = _cfg_get("term_blacklist", [])
    return set(w.lower().strip() for w in words if isinstance(w, str))

STOP_WORDS: set[str] = _load_blacklist()


def tokenize(text: str) -> list[str]:
    """分词并归一化：去标点、小写、过滤空串和格式占位符"""
    # 去掉 HTML 标签和 Minecraft 格式码
    cleaned = re.sub(r"<[^>]*>", " ", text)
    cleaned = re.sub(r"§[0-9a-fA-Fk-oK-OrR]", " ", cleaned)
    # 移除 printf 格式占位符 (%d, %s, %f, %.2f 等)
    cleaned = re.sub(r"%[+-]?\d*\.?\d*[dsf]", " ", cleaned)
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", cleaned.lower())
    return tokens


def ngram_key(ngram: tuple[str, ...]) -> str:
    return " ".join(ngram)


def extract_terms(
    en_data: dict[str, str],
    min_freq: int = 2,
    max_ngram: int = 3,
) -> dict:
    en_entries = [(k, v) for k, v in en_data.items() if isinstance(v, str)]

    uni_freq: defaultdict[str, int] = defaultdict(int)
    bi_freq: defaultdict[tuple, int] = defaultdict(int)
    tri_freq: defaultdict[tuple, int] = defaultdict(int)
    uni_keys: defaultdict[str, list[str]] = defaultdict(list)
    bi_keys: defaultdict[tuple, list[str]] = defaultdict(list)
    tri_keys: defaultdict[tuple, list[str]] = defaultdict(list)

    # ── 完整值短语：整句 token 序列也作为候选 n-gram ──
    full_freq: defaultdict[tuple, int] = defaultdict(int)
    full_keys: defaultdict[tuple, list[str]] = defaultdict(list)

    for key, value in en_entries:
        tokens = tokenize(value)
        if not tokens:
            continue
        n = len(tokens)

        # unigrams
        seen_uni: set[str] = set()
        for t in tokens:
            if t not in STOP_WORDS and t not in seen_uni:
                uni_freq[t] += 1
                uni_keys[t].append(key)
                seen_uni.add(t)

        # bigrams
        if max_ngram >= 2 and n >= 2:
            seen_bi: set[tuple] = set()
            for i in range(n - 1):
                bg = (tokens[i], tokens[i + 1])
                if bg not in seen_bi:
                    bi_freq[bg] += 1
                    bi_keys[bg].append(key)
                    seen_bi.add(bg)

        # trigrams
        if max_ngram >= 3 and n >= 3:
            seen_tri: set[tuple] = set()
            for i in range(n - 2):
                tg = (tokens[i], tokens[i + 1], tokens[i + 2])
                if tg not in seen_tri:
                    tri_freq[tg] += 1
                    tri_keys[tg].append(key)
                    seen_tri.add(tg)

        # 完整值短语（贪婪匹配）：整句也作为一个候选术语
        tup = tuple(tokens)
        if n >= 2:
            full_freq[tup] += 1
            full_keys[tup].append(key)

    # 把完整短语合并到对应 n-gram 桶中
    # 2 词的完整短语 → bigrams；3+ 词的 → trigrams（扩展 max_ngram 未覆盖的长度）
    # 注意：若该 n-gram 已在滑动窗口中被计数，不重复累加 freq，仅 extend 未出现过的 keys
    for tup in full_freq:
        n = len(tup)
        if n == 2:
            if tup not in bi_freq:
                bi_freq[tup] = full_freq[tup]
            for k in full_keys[tup]:
                if k not in bi_keys[tup]:
                    bi_keys[tup].append(k)
        elif n == 3:
            if tup not in tri_freq:
                tri_freq[tup] = full_freq[tup]
            for k in full_keys[tup]:
                if k not in tri_keys[tup]:
                    tri_keys[tup].append(k)
        else:
            # 4+ 词：也放入 trigram 桶以便后续提取
            if tup not in tri_freq:
                tri_freq[tup] = full_freq[tup]
            for k in full_keys[tup]:
                if k not in tri_keys[tup]:
                    tri_keys[tup].append(k)

    # ── build sorted result lists ──
    def build_list(
        freq_map: dict, keys_map: dict, min_f: int
    ) -> list[dict]:
        results = []
        max_keys = _cfg_get("max_keys_raw", 5)
        for term, freq in freq_map.items():
            if freq >= min_f:
                results.append({
                    "term": ngram_key(term) if isinstance(term, tuple) else term,
                    "freq": freq,
                    "keys": keys_map[term][:max_keys],
                })
        results.sort(key=lambda x: (-x["freq"], x["term"]))
        return results

    return {
        "unigrams": build_list(uni_freq, uni_keys, min_freq),
        "bigrams": build_list(bi_freq, bi_keys, min_freq),
        "trigrams": build_list(tri_freq, tri_keys, min_freq),
        "stats": {
            "total_entries": len(en_entries),
            "min_freq": min_freq,
            "max_ngram": max_ngram,
            "uni_count": len(build_list(uni_freq, uni_keys, min_freq)),
            "bi_count": len(build_list(bi_freq, bi_keys, min_freq)),
            "tri_count": len(build_list(tri_freq, tri_keys, min_freq)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 en_us.json 提取高频术语和短语"
    )
    parser.add_argument("--en", required=True, help="en_us.json 路径")
    parser.add_argument(
        "--min-freq", type=int, default=2,
        help="最低出现次数阈值，默认 2"
    )
    parser.add_argument(
        "--max-ngram", type=int, default=3,
        help="最大 n-gram 长度，默认 3"
    )

    args = parser.parse_args()

    try:
        with open(args.en, "r", encoding="utf-8-sig") as f:
            en_data = json.load(f)
    except FileNotFoundError as e:
        print(json.dumps({"error": f"文件未找到: {e}"}, ensure_ascii=False))
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON解析错误: {e}"}, ensure_ascii=False))
        sys.exit(1)

    result = extract_terms(en_data, args.min_freq, args.max_ngram)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
