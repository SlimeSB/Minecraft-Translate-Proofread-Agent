"""Phase 3a: 全自动格式检查。"""
from src.logging import info
from src.models import EntryDict, PipelineContext, VerdictDict
from src.checkers.format_checker import FormatChecker
from src.storage.database import PipelineDB


def run_phase3a(ctx: PipelineContext) -> None:
    info("[Phase 3a] 格式检查...")
    checker = FormatChecker()
    matched = ctx.alignment.get("matched_entries", [])
    all_v: list[VerdictDict] = []
    for entry in matched:
        all_v.extend(checker.check_all(entry))  # type: ignore[arg-type]

    # PR 模式：注入原文变更但翻译未变更的 warning
    if ctx.pr_mode and ctx.pr_warnings:
        for w in ctx.pr_warnings:
            key = w["key"]
            meta = ctx.pr_change_meta.get(key, {})
            all_v.append({
                "key": key,
                "verdict": "⚠️ SUGGEST",
                "source": "pr_warning",
                "reason": f"原文变更但翻译未变更。旧EN: {meta.get('old_en', '')[:60]!r} → 新EN: {ctx.en_data.get(key, '')[:60]!r}",
                "suggestion": "",
            })

    ctx.format_verdicts = all_v
    info(f"  格式问题: {len(all_v)} 条")
    if ctx.pr_warnings:
        info(f"  PR 警告注入: {len(ctx.pr_warnings)} 条")

    db = PipelineDB(ctx.output_dir / "pipeline.db")
    db.save_verdicts(all_v, "format")  # type: ignore[arg-type]
    db.close()
