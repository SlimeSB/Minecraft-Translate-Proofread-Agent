"""
报告生成器：合并所有 verdict来源、去重冲突解决、生成审校报告。

用法（独立）:
    python report_generator.py --alignment alignment.json \\
        --format-verdicts format_verdicts.json \\
        --term-verdicts term_verdicts.json \\
        --llm-verdicts llm_verdicts.json \\
        --output-dir ./output/

用法（模块）:
    from report_generator import ReportGenerator
    rg = ReportGenerator()
    rg.collect(format_v, term_v, llm_v)
    rg.generate(output_dir)
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════
# Verdict 优先级与去重
# ═══════════════════════════════════════════════════════════

# 优先级：FAIL > REVIEW > SUGGEST > PASS
VERDICT_PRIORITY: dict[str, int] = {
    "❌ FAIL": 4,
    "🔶 REVIEW": 3,
    "⚠️ SUGGEST": 2,
    "PASS": 1,
}

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
        passed = total - len(self.verdicts)  # 不在 verdicts 中的即 PASS
        # 如果有些 PASS 在 verdicts 中显式声明
        explicit_pass = sum(1 for v in self.verdicts if v.get("verdict") == "PASS")
        self.stats = {
            "total": total,
            "PASS": max(passed, explicit_pass),
            "⚠️ SUGGEST": suggest,
            "❌ FAIL": failed,
            "🔶 REVIEW": review,
        }
        return self.stats

    def generate_review_report(
        self,
        output_path: str,
    ) -> None:
        """生成 review_report.json —— 按来源分组，LLM 和程序化 verdict 并存。"""
        if not self.stats:
            self.compute_stats()

        # 构建 EN/ZH 速查表
        en_zh_map: dict[str, dict[str, str]] = {}
        for entry in self.matched_entries:
            en_zh_map[entry["key"]] = {"en": entry.get("en", ""), "zh": entry.get("zh", "")}

        # 统一规范化 verdict：统一字段名称、补齐 en_current/zh_current
        _VERDICT_MAP = {  # LLM 可能返回不标准的值
            "FAIL": "❌ FAIL", "REVIEW": "🔶 REVIEW", "SUGGEST": "⚠️ SUGGEST",
            "PASS": "PASS",
        }

        def _normalize(v: dict[str, Any]) -> dict[str, Any]:
            """统一所有 verdict 的字段结构与枚举值。"""
            out: dict[str, Any] = {
                "key":        v.get("key", ""),
                "en_current": v.get("en_current", ""),
                "zh_current": v.get("zh_current", ""),
                "verdict":    _VERDICT_MAP.get(v.get("verdict", ""), v.get("verdict", "")),
                "suggestion": v.get("suggestion", ""),
                "reason":     v.get("reason", ""),
                "source":     v.get("source", "other"),
            }
            if not out["en_current"] and not out["zh_current"]:
                pair = en_zh_map.get(out["key"], {})
                out["en_current"] = pair.get("en", "")
                out["zh_current"] = pair.get("zh", "")
            # 过滤 key 为 #N 的无效条目
            if not out["key"] or out["key"].startswith("#"):
                return None
            return out

        # 按来源分组
        by_source: dict[str, list[dict[str, Any]]] = {}
        for v in self.verdicts:
            nv = _normalize(v)
            if nv is None:
                continue
            src = nv["source"]
            by_source.setdefault(src, []).append(nv)

        # 合并视图（去重，最高优先级，用于统计）
        merged_raw = merge_verdicts(self.verdicts)
        merged = [nv for v in merged_raw if (nv := _normalize(v)) is not None]

        report = {
            "stats": self.stats,
            "by_source": {
                "format_check": by_source.get("format_check", []),
                "terminology_check": by_source.get("terminology_check", []),
                "llm_review": by_source.get("llm_review", []),
            },
            "merged": merged,
        }

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def generate_annotated_json(
        self,
        output_path: str,
    ) -> None:
        """
        生成 zh_cn_annotated.json —— 带 _comments 段的可读副本。
        仅对 ❌ FAIL 和 🔶 REVIEW 条目添加注释。
        """
        annotated: dict[str, Any] = {
            "_note": "仅供参考，不作为游戏读取文件。",
        }
        comments: dict[str, str] = {}

        for entry in self.matched_entries:
            key = entry["key"]
            zh = entry["zh"]

            # 构建 verdict 索引
            vs = [
                v for v in self.verdicts
                if v.get("key") == key and v.get("verdict") in ("❌ FAIL", "🔶 REVIEW")
            ]
            if vs:
                parts = []
                for v in vs:
                    part = f"{v['verdict']} — {v['reason']}"
                    if v.get("suggestion"):
                        part += f" → 建议: {v['suggestion']}"
                    parts.append(part)
                comments[key] = " | ".join(parts)

            annotated[key] = zh

        if comments:
            annotated["_comments"] = comments

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(annotated, f, ensure_ascii=False, indent=2)

    def print_summary(self) -> None:
        """打印审校摘要。"""
        if not self.stats:
            self.compute_stats()
        s = self.stats
        print("\n## 审校完毕")
        print(f"- 总计: {s['total']} 条 | PASS: {s['PASS']} | ⚠️ SUGGEST: {s['⚠️ SUGGEST']} | ❌ FAIL: {s['❌ FAIL']} | 🔶 REVIEW: {s['🔶 REVIEW']}")

        # 分类统计
        by_source = defaultdict(int)
        by_category = defaultdict(int)
        for v in self.verdicts:
            by_source[v.get("source", "unknown")] += 1
        if by_source:
            print("- 来源分布:", dict(by_source))

    def print_verdict_table(self, max_rows: int = 30) -> None:
        """打印非 PASS verdict 表格。"""
        non_pass = [v for v in self.verdicts if v.get("verdict") != "PASS"]
        if not non_pass:
            print("所有条目均 PASS ✓")
            return

        print(f"\n## 审校结论 ({len(non_pass)} 条)")
        print(f"| {'判定':<10} | {'键名':<45} | {'问题':<50} |")
        print(f"|{'-'*10}|{'-'*45}|{'-'*50}|")
        for v in non_pass[:max_rows]:
            key = v.get("key", "")[:42]
            reason = v.get("reason", "")[:48]
            verdict = v.get("verdict", "")
            print(f"| {verdict:<10} | {key:<45} | {reason:<50} |")
        if len(non_pass) > max_rows:
            print(f"... 还有 {len(non_pass) - max_rows} 条")


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="合并 verdict 并生成审校报告"
    )
    parser.add_argument("--alignment", required=True,
                        help="alignment.json 路径")
    parser.add_argument("--format-verdicts", default=None,
                        help="format_checker 输出的 verdicts JSON")
    parser.add_argument("--term-verdicts", default=None,
                        help="terminology_builder 输出的 verdicts JSON")
    parser.add_argument("--llm-verdicts", default=None,
                        help="LLM 输出的 verdicts JSON")
    parser.add_argument("--output-dir", required=True,
                        help="输出目录")

    args = parser.parse_args()

    # 加载 alignment
    try:
        with open(args.alignment, "r", encoding="utf-8") as f:
            alignment = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    rg = ReportGenerator()
    rg.load_alignment(alignment)

    # 加载各来源 verdicts
    verdict_lists: list[list[dict[str, Any]]] = []
    for path, label in [
        (args.format_verdicts, "format"),
        (args.term_verdicts, "term"),
        (args.llm_verdicts, "llm"),
    ]:
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    verdict_lists.append(data)
                elif isinstance(data, dict) and "verdicts" in data:
                    verdict_lists.append(data["verdicts"])
            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"警告: 无法加载 {label} verdicts: {e}")

    rg.collect(*verdict_lists)

    # 生成报告
    output_dir = Path(args.output_dir)
    review_path = output_dir / "review_report.json"
    annotated_path = output_dir / "zh_cn_annotated.json"

    rg.generate_review_report(str(review_path))
    rg.generate_annotated_json(str(annotated_path))

    print(f"审校报告已写入 {review_path}")
    print(f"可读注释版已写入 {annotated_path}")
    rg.print_summary()
    rg.print_verdict_table()


if __name__ == "__main__":
    main()
