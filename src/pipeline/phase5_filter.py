"""Phase 5: 最终 LLM 过滤 —— 审视已汇总的 verdict，筛除误报。"""
import json

from src.models import (
    EntryDict, FilterDiscardRecord, PipelineContext,
    ReviewReportDict, VerdictDict,
    VERDICT_FAIL, VERDICT_REVIEW, VERDICT_SUGGEST,
)
from src.llm.bridge import LLMBridge


def run_phase5(ctx: PipelineContext) -> None:
    if not ctx.llm_call or ctx.no_llm or ctx.dry_run:
        return

    print("[Phase 5] 最终 LLM 过滤...")
    review_path = ctx.output_dir / "06_review_report.json"
    with open(review_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    verdicts: list[VerdictDict] = report.get("verdicts", [])
    if not verdicts:
        print("  无 verdict 需要过滤")
        return

    # GuideME 条目不参与驳回审查
    guideme_keys: set[str] = {
        e["key"] for e in ctx.alignment.get("matched_entries", [])
        if e.get("format") == "guideme"
    }
    guideme_verdicts = [v for v in verdicts if v.get("key") in guideme_keys]
    review_verdicts = [v for v in verdicts if v.get("key") not in guideme_keys]
    if guideme_verdicts:
        print(f"  跳过 GuideME {len(guideme_verdicts)} 条")

    if not review_verdicts:
        print("  (仅 GuideME 条目，无需过滤)")
        return

    bridge = LLMBridge(ctx.llm_call, filter_llm_call=ctx.filter_llm_call)
    filtered, discard_records = bridge.filter_verdicts(review_verdicts)
    removed = len(discard_records)
    print(f"  驳回 {removed} 条, 保留 {len(filtered)} 条")

    filtered.extend(guideme_verdicts)

    discard_path = ctx.output_dir / "07_filter_discards.json"
    with open(discard_path, "w", encoding="utf-8") as f:
        json.dump(discard_records, f, ensure_ascii=False, indent=2)
    print(f"  驳回记录: {discard_path}")

    total = ctx.alignment["stats"]["matched"]
    report["stats"] = {
        "total": total,
        "PASS": total - len(filtered),
        VERDICT_SUGGEST: sum(1 for v in filtered if v.get("verdict") == VERDICT_SUGGEST),
        VERDICT_FAIL: sum(1 for v in filtered if v.get("verdict") == VERDICT_FAIL),
        VERDICT_REVIEW: sum(1 for v in filtered if v.get("verdict") == VERDICT_REVIEW),
    }
    report["verdicts"] = filtered
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  已更新: {review_path}")
