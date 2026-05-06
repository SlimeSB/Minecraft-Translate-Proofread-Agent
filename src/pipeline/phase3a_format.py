"""Phase 3a: 全自动格式检查。"""
import json

from src.models import PipelineContext
from src.checkers.format_checker import FormatChecker


def run_phase3a(ctx: PipelineContext) -> None:
    print("[Phase 3a] 格式检查...")
    checker = FormatChecker()
    matched = ctx.alignment.get("matched_entries", [])
    all_v: list[dict] = []
    for entry in matched:
        all_v.extend(checker.check_all(entry))

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
    print(f"  格式问题: {len(all_v)} 条")
    if ctx.pr_warnings:
        print(f"  PR 警告注入: {len(ctx.pr_warnings)} 条")

    _save_json(ctx.output_dir / "03_format_verdicts.json", {
        "total_checked": len(matched),
        "issues_found": len(all_v),
        "verdicts": all_v,
    })


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
