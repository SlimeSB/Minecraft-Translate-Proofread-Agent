"""Phase 3a: 全自动格式检查。"""
from src.logging import info
from src.models import EntryDict, PipelineContext, SOURCE_PR_WARNING, VerdictDict, update_diagnosis, verdict_str_to_int
from src.checkers.format_checker import FormatChecker


def run_phase3a(ctx: PipelineContext) -> None:
    info("[Phase 3a] 格式检查...")
    checker = FormatChecker()
    matched = ctx.alignment.get("matched_entries", [])
    all_v: list[VerdictDict] = []
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
                "source": SOURCE_PR_WARNING,
                "reason": f"原文变更但翻译未变更。旧EN: {meta.get('old_en', '')[:60]!r} → 新EN: {ctx.en_data.get(key, '')[:60]!r}",
                "suggestion": "",
            })

    info(f"  格式问题: {len(all_v)} 条")
    if ctx.pr_warnings:
        info(f"  PR 警告注入: {len(ctx.pr_warnings)} 条")

    # 6.1: Write verdicts directly to entries table
    db = ctx.db
    for v in all_v:
        key = v.get("key", "")
        if not key:
            continue
        checker_verdict = v.get("verdict", "PASS")
        verdict_int = verdict_str_to_int(checker_verdict)
        reason = v.get("reason", "")
        source = v.get("source", "format_check")

        diagnoses_json = update_diagnosis(db, key, source, reason)
        db.execute(
            "UPDATE entries SET state=MAX(state,1), verdict=MAX(verdict,?), diagnoses=? WHERE key=?",
            (verdict_int, diagnoses_json, key))

    # 6.2: Blanket push all entries to state >= 1 (idempotent)
    db.execute("UPDATE entries SET state=MAX(state,1)")
    db.commit()
