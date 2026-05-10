"""Phase 5: 报告生成 —— 从 DB 加载已过滤判决，生成 report.md + report.json。"""
import json

from src.logging import info
from src.models import (
    EntryDict, PipelineContext, VerdictDict,
    VERDICT_FAIL, VERDICT_REVIEW, VERDICT_SUGGEST,
)
from src.reporting.report_generator import ReportGenerator
from src.storage.database import PipelineDB


def run_phase5(ctx: PipelineContext) -> None:
    info("[Phase 5] 报告生成...")
    with PipelineDB(ctx.output_dir / "pipeline.db") as db:
        kept: list[VerdictDict] = db.load_verdicts(phase="merged", filtered=1)  # type: ignore[assignment]
        if not kept:
            kept = db.load_verdicts(phase="merged", filtered=0)  # type: ignore[assignment]

    # ── console 摘要 + 表格 ──
    rg = ReportGenerator()
    rg.load_alignment(ctx.alignment)
    rg.collect(kept)
    rg.print_summary()
    rg.print_verdict_table()

    # ── report.json ──
    ns_groups = _group_by_namespace(kept, ctx)
    # 仅保留非 PASS 的 verdict（已驳回的不写入 report.json）
    non_pass_verdicts = [v for v in kept if v.get("verdict") != "PASS"]
    report_data = {
        "verdicts": non_pass_verdicts,
        "alignment_stats": ctx.alignment.get("stats", {}),
        "by_namespace": ns_groups,
    }
    json_path = ctx.output_dir / "report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    # ── report.md（整体 PR 摘要）──
    _generate_summary_md(ctx, kept, ns_groups)

    # ── 按 namespace 分报告（含逐条 verdict 详情）──
    _generate_namespace_reports(ctx, kept, ns_groups)

    info(f"  总报告: {json_path}")
    info(f"  摘要: {ctx.output_dir / 'report.md'}")


def _build_ns_map(verdicts: list[VerdictDict], entries: list[EntryDict]) -> dict[str, list[VerdictDict]]:
    ns_map: dict[str, list[VerdictDict]] = {}
    for v in verdicts:
        k = v.get("key", "")
        matched = next((e for e in entries if e["key"] == k), None)
        ns = (matched.get("namespace") if matched else "") or v.get("namespace", "")
        if not ns:
            ns = "__default__"
        ns_map.setdefault(ns, []).append(v)
    return ns_map


def _group_by_namespace(verdicts: list[VerdictDict], ctx: PipelineContext) -> dict[str, dict]:
    entries = ctx.alignment.get("matched_entries", [])
    ns_map = _build_ns_map(verdicts, entries)

    result = {}
    for ns, vs in sorted(ns_map.items()):
        ns_total = sum(1 for e in entries if
                       (e.get("namespace") or "__default__") == ns
                       or (e["key"] in {vv.get("key") for vv in vs}))
        issues = [v for v in vs if v.get("verdict") != "PASS"]
        result[ns] = {
            "total": max(ns_total, len(vs)),
            "issues": len(issues),
            "fail": sum(1 for v in issues if v.get("verdict") == VERDICT_FAIL),
            "suggest": sum(1 for v in issues if v.get("verdict") == VERDICT_SUGGEST),
            "review": sum(1 for v in issues if v.get("verdict") == VERDICT_REVIEW),
        }
    return result


def _generate_namespace_reports(ctx: PipelineContext, verdicts: list[VerdictDict],
                                 ns_groups: dict[str, dict]) -> None:
    """为每个 namespace 生成独立报告，包含逐条 verdict 详情。"""
    entries = ctx.alignment.get("matched_entries", [])
    ns_map = _build_ns_map(verdicts, entries)

    if len(ns_map) <= 1 and "__default__" in ns_map:
        return

    ns_dir = ctx.output_dir
    ns_dir.mkdir(parents=True, exist_ok=True)

    for ns, vs in sorted(ns_map.items()):
        if ns == "__default__":
            continue
        issues = [v for v in vs if v.get("verdict") != "PASS"]
        if not issues:
            continue
        _generate_namespace_md(ns, issues, ns_groups.get(ns, {}), ns_dir)


def _generate_namespace_md(ns: str, verdicts: list[VerdictDict],
                            ns_info: dict, ns_dir) -> None:
    lines = [
        f"# {ns} — 翻译审校报告",
        "",
        f"- 条目总数：{ns_info.get('total', '?')}",
        f"- 问题：{ns_info.get('issues', len(verdicts))} 处",
        f"- ❌ FAIL：{ns_info.get('fail', 0)}",
        f"- ⚠️ SUGGEST：{ns_info.get('suggest', 0)}",
        f"- 🔶 REVIEW：{ns_info.get('review', 0)}",
        "",
        "## 问题清单",
        "",
        "| 判定 | 键名 | 问题 |",
        "|------|------|------|",
    ]

    # FAIL 在前，SUGGEST/REVIEW 在后
    sorted_vs = sorted(verdicts, key=lambda v: (
        0 if v.get("verdict") == VERDICT_FAIL else 1,
        v.get("key", ""),
    ))

    for v in sorted_vs:
        key = v.get("key", "")
        verdict = v.get("verdict", "")
        reason = v.get("reason", "")
        lines.append(f"| {verdict} | `{key}` | {reason} |")

    md_path = ns_dir / f"{ns}_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    info(f"  {ns}: {md_path}")


def _generate_summary_md(ctx: PipelineContext, verdicts: list[VerdictDict],
                          ns_groups: dict[str, dict]) -> None:
    total = len(ctx.alignment.get("matched_entries", []))
    fail = sum(1 for v in verdicts if v.get("verdict") == VERDICT_FAIL)
    suggest = sum(1 for v in verdicts if v.get("verdict") == VERDICT_SUGGEST)
    review = sum(1 for v in verdicts if v.get("verdict") == VERDICT_REVIEW)

    lines = [
        "# 翻译审校报告",
        "",
        f"共审校 **{total}** 条翻译，发现 **{len(verdicts)}** 处问题：",
        f"- ❌ FAIL：{fail} 处（必须修复）",
        f"- ⚠️ SUGGEST：{suggest} 处（建议改进）",
        f"- 🔶 REVIEW：{review} 处（需人工判断）",
        "",
        "## 按模组统计",
        "",
        "| 模组 | 总计 | 问题 | ❌ FAIL | ⚠️ SUGGEST | 🔶 REVIEW |",
        "|------|------|------|---------|-----------|----------|",
    ]

    for ns, info in ns_groups.items():
        lines.append(
            f"| {ns} | {info['total']} | {info['issues']} | "
            f"{info['fail']} | {info['suggest']} | {info['review']} |"
        )

    if ctx.pr_alignment:
        deletions = ctx.pr_alignment.get("deletions", {})
        if deletions:
            lines.append("")
            lines.append("## ⚠️ 兼容性警告")
            lines.append("")
            lines.append("以下模组本次 PR 删除了旧 key，使用旧版模组翻译的玩家可能遇到 key 缺失：")
            lines.append("")
            for ns, count in sorted(deletions.items()):
                if count > 0:
                    lines.append(f"- **{ns}**：删除 {count} 个 key")

    lines.append("")
    lines.append("## 各模组详细报告")
    lines.append("")
    for ns in sorted(ns_groups):
        if ns == "__default__":
            continue
        lines.append(f"- [{ns}]({ns}_report.md)")
    lines.append("")
    lines.append("")
    lines.append("> 完整数据见 report.json，可筛选查询所有 verdict 详情。")

    md_path = ctx.output_dir / "report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
