"""Verdict 合并：多来源 verdict 按 key 去重 + 统计。

用法:
    from src.verdict_merger import merge_verdicts, compute_merged_stats
    merged = merge_verdicts(format_v, term_v, llm_v)
    stats = compute_merged_stats(merged, total_entries=len(matched_entries))
"""
from collections import defaultdict
from collections.abc import Sequence

from src.models import VerdictDict, VERDICT_PRIORITY

SOURCE_PRIORITY: dict[str, int] = {
    "llm_review": 3,
    "interactive": 3,
    "format_check": 2,
    "terminology_check": 2,
    "llm_error": 1,
}


def merge_verdicts(
    *verdict_lists: Sequence[VerdictDict],
    keep_all: bool = False,
) -> list[VerdictDict]:
    """
    合并多个 verdict 列表，按 key 去重。
    同一 key 保留最高优先级的 verdict。

    :param keep_all: 如果为 True，保留同一 key 的所有 verdict（用于审查）
    :return: 合并后的 verdict 列表
    """
    if keep_all:
        all_v: list[VerdictDict] = []
        seen: set[tuple[str, str]] = set()
        for vl in verdict_lists:
            for v in vl:
                sig = (v.get("key", ""), v.get("reason", ""))
                if sig not in seen:
                    seen.add(sig)
                    all_v.append(v)
        return sorted(all_v, key=lambda v: VERDICT_PRIORITY.get(v.get("verdict", ""), 0), reverse=True)

    by_key: dict[str, list[VerdictDict]] = defaultdict(list)
    for vl in verdict_lists:
        for v in vl:
            key = v.get("key", "")
            if key:
                by_key[key].append(v)

    merged: list[VerdictDict] = []
    for key, verdicts in by_key.items():
        best = max(verdicts, key=lambda v: (
            VERDICT_PRIORITY.get(v.get("verdict", ""), 0),
            SOURCE_PRIORITY.get(v.get("source", ""), 0),
        ))
        reasons: list[str] = []
        for v in verdicts:
            r = v.get("reason", "")
            if r and r not in reasons:
                reasons.append(r)
        if len(reasons) > 1:
            best["reason"] = "; ".join(reasons)
        merged.append(best)

    return sorted(merged, key=lambda v: VERDICT_PRIORITY.get(v.get("verdict", ""), 0), reverse=True)


def compute_merged_stats(merged_verdicts: list[VerdictDict], total_entries: int) -> dict[str, int]:
    failed = sum(1 for v in merged_verdicts if v.get("verdict") == "❌ FAIL")
    suggest = sum(1 for v in merged_verdicts if v.get("verdict") == "⚠️ SUGGEST")
    review = sum(1 for v in merged_verdicts if v.get("verdict") == "🔶 REVIEW")
    passed = total_entries - failed - suggest - review
    return {
        "total": total_entries,
        "PASS": passed,
        "⚠️ SUGGEST": suggest,
        "❌ FAIL": failed,
        "🔶 REVIEW": review,
    }
