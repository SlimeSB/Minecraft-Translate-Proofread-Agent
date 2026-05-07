"""Phase 5: 最终 LLM 过滤 + 报告输出。

从 pipeline.db 读取合并后的判决，查过滤缓存，只对未命中条目调 LLM，
结果写回 DB 并生成 report.md。
"""
import json

from src.models import (
    EntryDict, FilterDiscardRecord, PipelineContext,
    VerdictDict,
    VERDICT_FAIL, VERDICT_REVIEW, VERDICT_SUGGEST,
)
from src.llm.bridge import LLMBridge
from src.reporting.report_generator import ReportGenerator
from src.storage.database import PipelineDB


def run_phase5(ctx: PipelineContext) -> None:
    if not ctx.llm_call or ctx.no_llm or ctx.dry_run:
        return

    print("[Phase 5] 最终 LLM 过滤...")
    db = PipelineDB(ctx.output_dir / "pipeline.db")

    verdicts = db.load_verdicts(phase="merged", filtered=0)
    if not verdicts:
        print("  无 verdict 需要过滤")
        db.close()
        return

    # GuideME 条目不参与驳回审查
    guideme_keys: set[str] = {
        e["key"] for e in ctx.alignment.get("matched_entries", [])
        if e.get("format") == "guideme"
    }
    guideme_verdicts = [v for v in verdicts if v["key"] in guideme_keys]
    review_verdicts = [v for v in verdicts if v["key"] not in guideme_keys]
    if guideme_verdicts:
        print(f"  跳过 GuideME {len(guideme_verdicts)} 条")

    if not review_verdicts:
        print("  (仅 GuideME 条目，无需过滤)")
        db.close()
        return

    # ── 查过滤缓存 ──
    cached_discard_keys: set[str] = set()
    cached_clean_reasons: dict[str, str] = {}
    uncached: list[VerdictDict] = []

    for v in review_verdicts:
        ck = _cache_key(v)
        result = db.lookup_filter_cache(ck)
        if result is not None:
            action, cleaned = result
            if action == "DISCARD":
                cached_discard_keys.add(v["key"])
            elif cleaned:
                cached_clean_reasons[v["key"]] = cleaned
        else:
            uncached.append(v)

    cache_hits = len(review_verdicts) - len(uncached)
    print(f"  缓存: {db.filter_cache_size()} 条, 命中 {cache_hits}, 需LLM {len(uncached)}")

    bridge = LLMBridge(ctx.llm_call, filter_llm_call=ctx.filter_llm_call)

    if uncached:
        filtered_uncached, discards_uncached = bridge.filter_verdicts(uncached)

        uncached_discard: set[str] = {d["key"] for d in discards_uncached}
        uncached_reasons: dict[str, str] = {}
        for v in filtered_uncached:
            k = v["key"]
            r = v.get("reason", "")
            if r and k not in uncached_discard:
                uncached_reasons[k] = r

        for v in uncached:
            ck = _cache_key(v)
            k = v["key"]
            if k in uncached_discard:
                db.store_filter_cache(ck, "DISCARD", "")
            else:
                db.store_filter_cache(ck, "KEEP", uncached_reasons.get(k, ""))
        db.commit_filter_cache()
    else:
        filtered_uncached: list[VerdictDict] = []
        discards_uncached: list[FilterDiscardRecord] = []
        uncached_discard = set()
        uncached_reasons = {}

    # ── 合并缓存 + LLM 结果 ──
    all_discard = cached_discard_keys | uncached_discard
    all_reasons = {**cached_clean_reasons, **uncached_reasons}

    for v in review_verdicts:
        k = v["key"]
        if k in all_discard:
            db.set_filtered(k, "DISCARD", "")
        else:
            if k in all_reasons:
                v["reason"] = all_reasons[k]
            db.set_filtered(k, "KEEP", v.get("reason", ""))

    # GuideME 自动保留
    for v in guideme_verdicts:
        db.set_filtered(v["key"], "KEEP", v.get("reason", ""))

    db.set_meta("filtered_stats", json.dumps(db.get_merged_stats(), ensure_ascii=False))

    removed = len(all_discard)
    kept = len(review_verdicts) - removed
    print(f"  驳回 {removed} 条, 保留 {kept} 条")

    db.close()

    # ── 生成 report.md（从 DB 加载过滤后数据） ──
    db2 = PipelineDB(ctx.output_dir / "pipeline.db")
    kept_verdicts = db2.load_verdicts(phase="merged", filtered=1)
    _generate_markdown_report(ctx, kept_verdicts)
    db2.close()

    # ── 按 namespace 生成质量报告 ──
    _generate_namespace_reports(ctx)


def _cache_key(v: dict) -> str:
    import hashlib
    raw = ":".join([
        v.get("key", ""),
        v.get("verdict", ""),
        (v.get("zh_current") or v.get("zh_current", ""))[:150],
        v.get("reason", "")[:200],
    ])
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()


def _generate_markdown_report(ctx: PipelineContext, verdicts: list[VerdictDict]) -> None:
    rg = ReportGenerator()
    rg.load_alignment(ctx.alignment)
    rg.verdicts = verdicts
    rg.compute_stats()
    md_path = ctx.output_dir / "report.md"
    rg.generate_markdown_report(str(md_path))
    print(f"  审校报告: {md_path}")


def _generate_namespace_reports(ctx: PipelineContext) -> None:
    if not ctx.llm_call:
        return

    db = PipelineDB(ctx.output_dir / "pipeline.db")
    kept = db.load_verdicts(phase="merged", filtered=1)
    db.close()

    ns_map: dict[str, list[VerdictDict]] = {}
    for v in kept:
        matched = next((e for e in ctx.alignment.get("matched_entries", [])
                        if e["key"] == v.get("key")), None)
        ns = (matched.get("namespace") if matched else "") or v.get("namespace", "")
        if ns:
            ns_map.setdefault(ns, []).append(v)

    if not ns_map:
        return

    ns_dir = ctx.output_dir / "namespaces"
    for ns, ns_verdicts in ns_map.items():
        ns_path = ns_dir / ns
        ns_path.mkdir(parents=True, exist_ok=True)
        _generate_llm_report(ctx, ns, ns_verdicts, ns_path / "report.md")


def _generate_llm_report(
    ctx: PipelineContext,
    ns: str,
    verdicts: list[VerdictDict],
    output_path,
) -> None:
    ns_entries = [e for e in ctx.alignment.get("matched_entries", [])
                  if e.get("namespace") == ns]
    total = len(ns_entries)

    fail_count = sum(1 for v in verdicts if v.get("verdict") == VERDICT_FAIL)
    suggest_count = sum(1 for v in verdicts if v.get("verdict") == VERDICT_SUGGEST)
    review_count = sum(1 for v in verdicts if v.get("verdict") == VERDICT_REVIEW)

    format_v = [v for v in verdicts if v.get("source") == "format_check"]
    term_v = [v for v in verdicts if v.get("source") == "terminology_check"]
    llm_v = [v for v in verdicts if v.get("source") == "llm_review"]

    lines = [
        f"## {ns} — 翻译审校报告",
        "",
        f"共审校 **{total}** 条翻译，发现 **{len(verdicts)}** 处问题：",
        f"- {fail_count} 处必须修复（❌ FAIL）",
        f"- {suggest_count} 处建议改进（⚠️ SUGGEST）",
        f"- {review_count} 处需人工判断（🔶 REVIEW）",
    ]

    if format_v:
        lines.append("")
        lines.append("### 格式问题")
        for v in format_v[:10]:
            lines.append(f"- `{v['key']}` — {v.get('reason', '')}")
        if len(format_v) > 10:
            lines.append(f"- ... 还有 {len(format_v) - 10} 条")

    if term_v:
        lines.append("")
        lines.append("### 术语一致性")
        for v in term_v[:10]:
            lines.append(f"- `{v['key']}` — {v.get('reason', '')}")
        if len(term_v) > 10:
            lines.append(f"- ... 还有 {len(term_v) - 10} 条")

    if llm_v:
        lines.append("")
        lines.append("### LLM 审校发现")
        for v in llm_v[:10]:
            lines.append(f"- `{v['key']}` — {v.get('reason', '')}")
            if v.get('suggestion'):
                lines.append(f"  建议: {v['suggestion']}")
        if len(llm_v) > 10:
            lines.append(f"- ... 还有 {len(llm_v) - 10} 条")

    del_count = ctx.pr_alignment.get("deletions", {}).get(ns, 0) if ctx.pr_alignment else 0
    if del_count > 0:
        lines.append("")
        lines.append("### ⚠️ 兼容性警告")
        lines.append(f"本次 PR 删除了 **{del_count}** 个旧 key（已从仓库移除），使用旧版模组翻译的玩家可能遇到 key 缺失。")

    prompt = (
        f"你是Minecraft模组简中翻译审校专家。以下是 {ns} 模组的翻译审校结果摘要，"
        f"请用简洁自然的中文评价翻译质量，指出主要问题和改进方向。"
        f"保持一段话，不要重复数据，不要用列表格式。\n\n"
        + "\n".join(lines)
    )

    try:
        review_text = ctx.llm_call(prompt)
        full_report = "\n\n".join(["\n".join(lines), "## 总体评价", review_text.strip()])
    except Exception:
        full_report = "\n".join(lines) + "\n\n## 总体评价\n（LLM 生成失败）"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_report)
    print(f"  质量报告: {output_path}")
