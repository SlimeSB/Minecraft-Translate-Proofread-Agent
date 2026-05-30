"""Phase 4: 最终 LLM 过滤。

从 entries 表读取 state=2 且有问题的条目，调 LLM 过滤，
结果写回 DB（驳回 → verdict=0, state=3；保留 → state=3，维持原 verdict）。
"""
from src.logging import info, debug
from src.models import PipelineContext, VerdictDict, _format_diagnoses, verdict_int_to_str
from src.llm.bridge import LLMBridge


def run_phase4(ctx: PipelineContext) -> None:
    if not ctx.llm_call or ctx.no_llm or ctx.dry_run:
        return

    info("[Phase 4] 最终 LLM 过滤...")
    db = ctx.db

    # 9.1: Load verdicts from entries table (state=2=reviewed, unfiltered; only problematic)
    rows = db.execute(
        "SELECT * FROM entries WHERE state=2 AND verdict >= 1"
    ).fetchall()
    if not rows:
        info("  无 verdict 需要过滤")
        return

    verdicts: list[VerdictDict] = []
    for r in rows:
        verdicts.append({
            "key": r["key"],
            "en_current": r["en"],
            "zh_current": r["zh"],
            "verdict": verdict_int_to_str(r["verdict"], llm=True),
            "reason": _format_diagnoses(r["diagnoses"]),
            "suggestion": r["suggestion"] or "",
        })

    info(f"  待过滤: {len(verdicts)} 条")

    bridge = LLMBridge(ctx.llm_call, filter_llm_call=ctx.filter_llm_call)
    filtered_uncached, passes_uncached = bridge.filter_verdicts(verdicts)

    pass_keys: set[str] = {d["key"] for d in passes_uncached}

    # 9.3: Write filter results directly to entries table
    for v in verdicts:
        k = v["key"]
        if k in pass_keys:
            # 驳回 → PASS (verdict=0, state=3)
            db.execute("UPDATE entries SET state=3, verdict=0 WHERE key=?", (k,))
            debug(f"  [过滤·驳回] {k}: {v.get('verdict', '')} → PASS")
        else:
            # 保留 → state=3, maintain verdict
            db.execute("UPDATE entries SET state=3 WHERE key=?", (k,))
            debug(f"  [过滤·保留] {k}: 维持 {v.get('verdict', '')}")

    removed = len(pass_keys)
    kept = len(verdicts) - removed

    # 9.4: Stats via SELECT COUNT
    total_count = db.execute("SELECT COUNT(*) FROM entries WHERE state=3").fetchone()[0]
    pass_count = db.execute("SELECT COUNT(*) FROM entries WHERE state=3 AND verdict=0").fetchone()[0]
    suggest_count = db.execute("SELECT COUNT(*) FROM entries WHERE state=3 AND verdict=1").fetchone()[0]
    review_count = db.execute("SELECT COUNT(*) FROM entries WHERE state=3 AND verdict=2").fetchone()[0]
    fail_count = db.execute("SELECT COUNT(*) FROM entries WHERE state=3 AND verdict=3").fetchone()[0]

    db.commit()
    info(f"  驳回(PASS) {removed} 条, 保留 {kept} 条")
    info(f"  过滤后统计: 总计{total_count} | PASS {pass_count} | SUGGEST {suggest_count} | REVIEW {review_count} | FAIL {fail_count}")
