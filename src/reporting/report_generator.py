"""
报告生成器：合并所有 verdict来源、去重冲突解决、生成审校报告。

用法:
    from report_generator import ReportGenerator
    rg = ReportGenerator()
    rg.collect(format_v, term_v, llm_v)
    rg.generate(output_dir)
"""
import sys
from collections import defaultdict
from typing import Any


def _print(*args, **kwargs) -> None:
    """安全打印，应对 Windows GBK 终端无法输出 emoji 的情况。"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe = [
            str(a).encode(encoding, errors="replace").decode(encoding)
            for a in args
        ]
        print(*safe, **kwargs)


from src.models import VERDICT_PRIORITY  # noqa: E402

# ═══════════════════════════════════════════════════════════
# Verdict 优先级与去重
# ═══════════════════════════════════════════════════════════

# 来源优先级：LLM 手动审校 > 格式自动检查 > 术语自动检查
# 同一条目同级别时，手动判断优先
SOURCE_PRIORITY: dict[str, int] = {
    "llm_review": 3,
    "interactive": 3,
    "format_check": 2,
    "terminology_check": 2,
    "llm_error": 1,
}


def merge_verdicts(
    *verdict_lists: list[dict[str, Any]],
    keep_all: bool = False,
) -> list[dict[str, Any]]:
    """
    合并多个 verdict 列表，按 key 去重。
    同一 key 保留最高优先级的 verdict。

    :param keep_all: 如果为 True，保留同一 key 的所有 verdict（用于审查）
    :return: 合并后的 verdict 列表
    """
    if keep_all:
        all_v: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for vl in verdict_lists:
            for v in vl:
                sig = (v.get("key", ""), v.get("reason", ""))
                if sig not in seen:
                    seen.add(sig)
                    all_v.append(v)
        return sorted(all_v, key=lambda v: VERDICT_PRIORITY.get(v.get("verdict", ""), 0), reverse=True)

    # 按 key 归并
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vl in verdict_lists:
        for v in vl:
            key = v.get("key", "")
            if key:
                by_key[key].append(v)

    merged: list[dict[str, Any]] = []
    for key, verdicts in by_key.items():
        # 选最高优先级
        best = max(verdicts, key=lambda v: (
            VERDICT_PRIORITY.get(v.get("verdict", ""), 0),
            SOURCE_PRIORITY.get(v.get("source", ""), 0),
        ))
        # 收集所有 reason 去重
        reasons: list[str] = []
        for v in verdicts:
            r = v.get("reason", "")
            if r and r not in reasons:
                reasons.append(r)
        if len(reasons) > 1:
            best["reason"] = "; ".join(reasons)
        merged.append(best)

    return sorted(merged, key=lambda v: VERDICT_PRIORITY.get(v.get("verdict", ""), 0), reverse=True)


# ═══════════════════════════════════════════════════════════
# 报告生成器
# ═══════════════════════════════════════════════════════════

class ReportGenerator:
    """收集 verdict 并生成审校报告。"""

    def __init__(self):
        self.alignment: dict[str, Any] = {}
        self.matched_entries: list[dict[str, str]] = []
        self.verdicts: list[dict[str, Any]] = []
        self.stats: dict[str, int] = {}

    def load_alignment(self, alignment: dict[str, Any]) -> None:
        """加载对齐数据。"""
        self.alignment = alignment
        self.matched_entries = alignment.get("matched_entries", [])

    def collect(self, *verdict_lists: list[dict[str, Any]]) -> None:
        """收集并合并所有 verdict。"""
        self.verdicts = merge_verdicts(*verdict_lists)

    def compute_stats(self) -> dict[str, int]:
        """计算审校统计。"""
        total = len(self.matched_entries)
        failed = sum(1 for v in self.verdicts if v.get("verdict") == "❌ FAIL")
        suggest = sum(1 for v in self.verdicts if v.get("verdict") == "⚠️ SUGGEST")
        review = sum(1 for v in self.verdicts if v.get("verdict") == "🔶 REVIEW")
        passed = total - failed - suggest - review
        self.stats = {
            "total": total,
            "PASS": passed,
            "⚠️ SUGGEST": suggest,
            "❌ FAIL": failed,
            "🔶 REVIEW": review,
        }
        return self.stats

    def build_report(
        self,
    ) -> dict[str, Any]:
        """构建报告 dict（不写磁盘），供调用方自行存储。"""
        if not self.stats:
            self.compute_stats()

        en_zh_map: dict[str, dict[str, str]] = {}
        namespace_map: dict[str, str] = {}
        for entry in self.matched_entries:
            key = entry["key"]
            en_zh_map[key] = {"en": entry.get("en", ""), "zh": entry.get("zh", "")}
            ns = entry.get("namespace", "")
            if ns:
                namespace_map[key] = ns

        _VERDICT_MAP = {
            "FAIL": "❌ FAIL", "REVIEW": "🔶 REVIEW", "SUGGEST": "⚠️ SUGGEST",
            "PASS": "PASS",
        }

        def _normalize(v: dict[str, Any]) -> dict[str, Any] | None:
            out: dict[str, Any] = {
                "key":        v.get("key", ""),
                "en_current": v.get("en_current", ""),
                "zh_current": v.get("zh_current", ""),
                "verdict":    _VERDICT_MAP.get(v.get("verdict", ""), v.get("verdict", "")),
                "suggestion": v.get("suggestion", ""),
                "reason":     v.get("reason", ""),
                "source":     v.get("source", ""),
                "namespace":  v.get("namespace") or namespace_map.get(v.get("key", ""), ""),
            }
            if not out["en_current"] and not out["zh_current"]:
                pair = en_zh_map.get(out["key"], {})
                out["en_current"] = pair.get("en", "")
                out["zh_current"] = pair.get("zh", "")
            if not out["key"] or out["key"].startswith("#"):
                return None
            return out

        by_key: dict[str, dict[str, Any]] = {}
        for v in self.verdicts:
            nv = _normalize(v)
            if nv is None:
                continue
            key = nv["key"]
            if key not in by_key:
                by_key[key] = nv
                continue
            existing = by_key[key]
            reasons: set[str] = set()
            for r in (existing["reason"], nv["reason"]):
                for part in r.split("; "):
                    part = part.strip()
                    if part:
                        reasons.add(part)
            existing["reason"] = "; ".join(reasons)
            if VERDICT_PRIORITY.get(nv["verdict"], 0) > VERDICT_PRIORITY.get(existing["verdict"], 0):
                existing["verdict"] = nv["verdict"]
                existing["suggestion"] = nv["suggestion"] or existing["suggestion"]

        merged = sorted(
            by_key.values(),
            key=lambda v: VERDICT_PRIORITY.get(v["verdict"], 0),
            reverse=True,
        )

        return {
            "stats": dict(self.stats),
            "verdicts": merged,
        }

    def print_summary(self) -> None:
        """打印审校摘要。"""
        if not self.stats:
            self.compute_stats()
        s = self.stats
        _print("\n## 审校完毕")
        _print(f"- 总计: {s['total']} 条 | PASS: {s['PASS']} | ⚠️ SUGGEST: {s['⚠️ SUGGEST']} | ❌ FAIL: {s['❌ FAIL']} | 🔶 REVIEW: {s['🔶 REVIEW']}")

        # 分类统计
        by_source = defaultdict(int)
        by_category = defaultdict(int)
        for v in self.verdicts:
            by_source[v.get("source", "unknown")] += 1
        if by_source:
            _print("- 来源分布:", dict(by_source))

    def print_verdict_table(self, max_rows: int = 30) -> None:
        """打印非 PASS verdict 表格。"""
        non_pass = [v for v in self.verdicts if v.get("verdict") != "PASS"]
        if not non_pass:
            _print("所有条目均 PASS ✓")
            return

        _print(f"\n## 审校结论 ({len(non_pass)} 条)")
        _print(f"| {'判定':<10} | {'键名':<45} | {'问题':<50} |")
        _print(f"|{'-'*10}|{'-'*45}|{'-'*50}|")
        for v in non_pass[:max_rows]:
            key = v.get("key", "")[:42]
            reason = v.get("reason", "")[:48]
            verdict = v.get("verdict", "")
            _print(f"| {verdict:<10} | {key:<45} | {reason:<50} |")
        if len(non_pass) > max_rows:
            _print(f"... 还有 {len(non_pass) - max_rows} 条")

