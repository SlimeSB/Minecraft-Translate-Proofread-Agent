"""Phase 5: 报告生成 —— 从 entries 表加载 verdict，生成 report.md + report.json。"""
import json

from src.logging import info
from src.models import (
    EntryDict, PipelineContext, VerdictDict,
    VERDICT_FAIL, VERDICT_REVIEW, VERDICT_SUGGEST, VERDICT_PASS,
    merge_diagnoses_for_report, verdict_int_to_str,
)
from src.config import DEFAULT_NAMESPACE
from src.reporting.report_generator import ReportGenerator


def run_phase5(ctx: PipelineContext) -> None:
    info("[Phase 5] 报告生成...")
    db = ctx.db

    # 10.1: Load entries with verdict >= 1 (all problematic entries)
    rows = db.execute("SELECT * FROM entries WHERE verdict >= 1").fetchall()
    kept: list[VerdictDict] = []
    for r in rows:
        kept.append({
            "key": r["key"],
            "en_current": r["en"],
            "zh_current": r["zh"],
            "verdict": verdict_int_to_str(r["verdict"]),
            "reason": merge_diagnoses_for_report(r["diagnoses"]),
            "suggestion": r["suggestion"] or "",
            "source": "",
            "namespace": r["namespace"] or "",
            "version": r["version"] or "",
            "file_path": r["file_path"] or "",
        })

    # 10.3: Load glossary from output_dir/glossary.json
    glossary_path = ctx.output_dir / "glossary.json"
    glossary: list = []
    if glossary_path.exists():
        with open(glossary_path, "r", encoding="utf-8") as f:
            glossary = json.load(f)
    if not glossary:
        glossary = ctx.glossary

    # ── console 摘要 + 表格 ──
    rg = ReportGenerator()
    rg.load_alignment(ctx.alignment)
    rg.collect(kept)
    rg.print_summary()
    rg.print_verdict_table()

    # ── report.json ──
    non_pass_verdicts = [v for v in kept if v.get("verdict") != "PASS"]
    report_data = {
        "verdicts": non_pass_verdicts,
        "alignment_stats": ctx.alignment.get("stats", {}),
    }
    json_path = ctx.output_dir / "report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    # ── glossary.json ──
    with open(glossary_path, "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)
    info(f"  术语表: {glossary_path}")

    # ── report.md（整体摘要）──
    entries = ctx.alignment.get("matched_entries", [])
    if ctx.pr_mode and ctx.pr_version_groups:
        groups_3d = _build_slug_ver_ns_map(kept, entries)
        _generate_summary_md_3level(ctx, kept, groups_3d)
        _generate_namespace_reports_3level(ctx, kept, groups_3d)
    else:
        ns_groups = _group_by_namespace(kept, ctx, entries)
        _generate_summary_md(ctx, kept, entries, ns_groups)
        _generate_namespace_reports(ctx, kept, entries, ns_groups)

    info(f"  总报告: {json_path}")
    info(f"  摘要: {ctx.output_dir / 'report.md'}")


# ═══════════════════════════════════════════════════════════
# 传统模式 helper（保持向后兼容）
# ═══════════════════════════════════════════════════════════

def _build_ns_map(verdicts: list[VerdictDict], entries: list[EntryDict]) -> dict[str, list[VerdictDict]]:
    ns_map: dict[str, list[VerdictDict]] = {}
    for v in verdicts:
        k = v.get("key", "")
        matched = next((e for e in entries if e["key"] == k), None)
        ns = (matched.get("namespace") if matched else "") or v.get("namespace", "")
        if not ns:
            ns = DEFAULT_NAMESPACE
        ns_map.setdefault(ns, []).append(v)
    return ns_map


def _group_by_namespace(verdicts: list[VerdictDict], ctx: PipelineContext, entries: list[EntryDict]) -> dict[str, dict]:
    ns_map = _build_ns_map(verdicts, entries)
    result = {}
    for ns, vs in sorted(ns_map.items()):
        issues = [v for v in vs if v.get("verdict") != "PASS"]
        result[ns] = {
            "total": sum(1 for e in entries if (e.get("namespace") or DEFAULT_NAMESPACE) == ns) or len(vs),
            "issues": len(issues),
            "fail": sum(1 for v in issues if v.get("verdict") == VERDICT_FAIL),
            "suggest": sum(1 for v in issues if v.get("verdict") == VERDICT_SUGGEST),
            "review": sum(1 for v in issues if v.get("verdict") == VERDICT_REVIEW),
        }
    return result


def _generate_summary_md(ctx: PipelineContext, verdicts: list[VerdictDict],
                          entries: list[EntryDict], ns_groups: dict[str, dict]) -> None:
    total = len(entries)
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

    lines.append("")
    lines.append("## 各模组详细报告")
    lines.append("")
    for ns in sorted(ns_groups):
        if ns == DEFAULT_NAMESPACE:
            continue
        lines.append(f"- [{ns}]({ns}/{ns}_report.md)")
    lines.append("")
    lines.append("> 完整数据见 report.json，可筛选查询所有 verdict 详情。")

    md_path = ctx.output_dir / "report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _generate_namespace_reports(ctx: PipelineContext, verdicts: list[VerdictDict],
                                 entries: list[EntryDict], ns_groups: dict[str, dict]) -> None:
    ns_map = _build_ns_map(verdicts, entries)
    if len(ns_map) <= 1 and DEFAULT_NAMESPACE in ns_map:
        return
    for ns, vs in sorted(ns_map.items()):
        if ns == DEFAULT_NAMESPACE:
            continue
        issues = [v for v in vs if v.get("verdict") != "PASS"]
        if not issues:
            continue
        ns_dir = ctx.output_dir / ns
        ns_dir.mkdir(parents=True, exist_ok=True)
        _generate_namespace_md(ns, issues, ns_groups.get(ns, {}), ns_dir, None)
        _generate_namespace_json(ns, issues, ns_groups.get(ns, {}), ns_dir)


# ═══════════════════════════════════════════════════════════
# PR 多版本模式 helper（三级目录结构）
# ═══════════════════════════════════════════════════════════


def _build_slug_ver_ns_map(
    verdicts: list[VerdictDict], entries: list[EntryDict],
) -> dict[str, dict[str, dict[str, dict]]]:
    """构建 slug → version → namespace → {stats, verdicts} 的四级映射。"""
    result: dict[str, dict[str, dict[str, dict]]] = {}
    entry_lookup = {e["key"]: e for e in entries}
    for v in verdicts:
        matched = entry_lookup.get(v.get("key", ""), {})
        slug = (matched.get("slug") if matched else "") or v.get("slug", "") or ""
        ver = v.get("version", "")
        ns = v.get("namespace", "") or DEFAULT_NAMESPACE

        if not slug:
            slug = ns

        result.setdefault(slug, {}).setdefault(ver, {}).setdefault(ns, {"total": 0, "issues": 0, "fail": 0, "suggest": 0, "review": 0, "verdicts": []})

        info_dict = result[slug][ver][ns]
        info_dict["verdicts"].append(v)
        info_dict["total"] += 1
        if v.get("verdict") != "PASS":
            info_dict["issues"] += 1
        if v.get("verdict") == VERDICT_FAIL:
            info_dict["fail"] += 1
        elif v.get("verdict") == VERDICT_SUGGEST:
            info_dict["suggest"] += 1
        elif v.get("verdict") == VERDICT_REVIEW:
            info_dict["review"] += 1

    return result


def _generate_namespace_reports_3level(
    ctx: PipelineContext, verdicts: list[VerdictDict],
    groups: dict[str, dict[str, dict[str, dict]]],
) -> None:
    for slug, versions in sorted(groups.items()):
        for ver, namespaces in sorted(versions.items()):
            for ns, info in sorted(namespaces.items()):
                issues = [v for v in info["verdicts"] if v.get("verdict") != "PASS"]
                if not issues:
                    continue
                ns_dir = ctx.output_dir / slug / ver / ns
                ns_dir.mkdir(parents=True, exist_ok=True)
                _generate_namespace_md(ns, issues, info, ns_dir, ctx.pr_version_groups.get(slug))
                _generate_namespace_json(ns, issues, info, ns_dir)


def _generate_summary_md_3level(
    ctx: PipelineContext, verdicts: list[VerdictDict],
    groups: dict[str, dict[str, dict[str, dict]]],
) -> None:
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
    ]

    for slug, versions in sorted(groups.items()):
        slug_total = sum(info["total"] for ver_ns in versions.values() for info in ver_ns.values())
        slug_issues = sum(info["issues"] for ver_ns in versions.values() for info in ver_ns.values())
        lines.append(f"## {slug}（共 {slug_total} 条目，{slug_issues} 问题）")
        lines.append("")

        # 版本差异链可视化
        vg = ctx.pr_version_groups.get(slug) if ctx.pr_version_groups else None
        if vg and len(vg["versions"]) >= 2:
            chain_parts: list[str] = []
            for i, ver in enumerate(vg["versions"]):
                chain_parts.append(ver)
                if i < len(vg["versions"]) - 1:
                    diff = vg["cross_version_diffs"].get(vg["versions"][i + 1])
                    if diff:
                        added = len(diff.added_keys)
                        modified = len(diff.modified_keys)
                        chain_parts.append(f"──(+{added}/+改{modified})──▶")
                    else:
                        chain_parts.append("──▶")
            lines.append("**版本差异链**: " + " ".join(chain_parts))
            lines.append("")

            for i in range(1, len(vg["versions"])):
                cur_ver = vg["versions"][i]
                ref_ver = vg["versions"][i - 1]
                diff = vg["cross_version_diffs"].get(cur_ver)
                if not diff:
                    continue
                if diff.added_keys or diff.modified_keys:
                    lines.append(f"### {cur_ver} ──▶ {ref_ver}")
                    if diff.added_keys:
                        lines.append("")
                        lines.append("**新增 key：**")
                        lines.append("")
                        lines.append("| key | EN | ZH |")
                        lines.append("|-----|----|----|")
                        vdata = vg["version_data"].get(cur_ver)
                        for k in diff.added_keys:
                            en_v = vdata["full_en"].get(k, "") if vdata else ""
                            zh_v = vdata["full_zh"].get(k, "") if vdata else ""
                            lines.append(f"| `{k}` | {en_v[:80]} | {zh_v[:80]} |")
                        lines.append("")
                    if diff.modified_keys:
                        lines.append("")
                        lines.append("**修改 key：**")
                        lines.append("")
                        lines.append("| key | 当前 EN | 当前 ZH | ref EN | ref ZH |")
                        lines.append("|-----|---------|---------|--------|--------|")
                        vdata = vg["version_data"].get(cur_ver)
                        for k in diff.modified_keys:
                            cur_en = vdata["full_en"].get(k, "") if vdata else ""
                            cur_zh = vdata["full_zh"].get(k, "") if vdata else ""
                            ref = diff.key_refs.get(k, {})
                            ref_en = ref.get("ref_en", "")
                            ref_zh = ref.get("ref_zh", "")
                            lines.append(f"| `{k}` | {cur_en[:60]} | {cur_zh[:60]} | {ref_en[:60]} | {ref_zh[:60]} |")
                        lines.append("")

        for ver in sorted(versions.keys(), reverse=True):
            namespaces = versions[ver]
            for ns in sorted(namespaces.keys()):
                info = namespaces[ns]
                if info["issues"] == 0:
                    continue
                if len(versions) > 1:
                    lines.append(f"- [{ver}/{ns}]({slug}/{ver}/{ns}/report.md) — {info['issues']} 问题")
                else:
                    lines.append(f"- [{ns}]({slug}/{ver}/{ns}/report.md) — {info['issues']} 问题")
        lines.append("")

    lines.append("> 完整数据见 report.json，可筛选查询所有 verdict 详情。")

    md_path = ctx.output_dir / "report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _generate_namespace_json(ns: str, verdicts: list[VerdictDict],
                              ns_info: dict, ns_dir) -> None:
    version_groups: dict[str, dict] = {}
    for v in verdicts:
        ver = v.get("version", "") or DEFAULT_NAMESPACE
        if ver not in version_groups:
            version_groups[ver] = {"count": 0, "verdicts": []}
        version_groups[ver]["verdicts"].append(v)
        version_groups[ver]["count"] += 1

    data = {
        "namespace": ns,
        "stats": {
            "total": ns_info.get("total", len(verdicts)),
            "issues": ns_info.get("issues", len(verdicts)),
            "fail": ns_info.get("fail", 0),
            "suggest": ns_info.get("suggest", 0),
            "review": ns_info.get("review", 0),
        },
        "version_groups": version_groups,
    }

    json_path = ns_dir / f"{ns}_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _generate_namespace_md(ns: str, verdicts: list[VerdictDict],
                            ns_info: dict, ns_dir,
                            version_group=None) -> None:
    lines = [
        f"# {ns} — 翻译审校报告",
        "",
        f"- 条目总数：{ns_info.get('total', '?')}",
        f"- 问题：{ns_info.get('issues', len(verdicts))} 处",
        f"- ❌ FAIL：{ns_info.get('fail', 0)}",
        f"- ⚠️ SUGGEST：{ns_info.get('suggest', 0)}",
        f"- 🔶 REVIEW：{ns_info.get('review', 0)}",
        "",
    ]

    by_version: dict[str, list[VerdictDict]] = {}
    for v in verdicts:
        ver = v.get("version", "") or ""
        by_version.setdefault(ver, []).append(v)

    versions = sorted(by_version.keys())
    multi_version = len(versions) > 1

    for ver in versions:
        vs = by_version[ver]
        sorted_vs = sorted(vs, key=lambda v: (
            0 if v.get("verdict") == VERDICT_FAIL else 1,
            v.get("key", ""),
        ))

        if multi_version and ver:
            lines.append(f"## 版本 {ver}")
            lines.append("")

        lines.append("| 判定 | 键名 | 文件路径 | 问题 |")
        lines.append("|------|------|----------|------|")

        for v in sorted_vs:
            key = v.get("key", "")
            verdict = v.get("verdict", "")
            reason = v.get("reason", "")
            file_path = v.get("file_path", "")
            lines.append(f"| {verdict} | `{key}` | `{file_path}` | {reason} |")

        lines.append("")

    md_path = ns_dir / "report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    # 日志输出相对路径
    try:
        rel = md_path.relative_to(ns_dir.parents[1]) if len(ns_dir.parents) >= 2 else md_path
    except (ValueError, IndexError):
        rel = md_path
    info(f"  {ns}: {rel}")
