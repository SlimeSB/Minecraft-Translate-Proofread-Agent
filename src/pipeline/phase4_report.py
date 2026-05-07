"""Phase 4: 报告生成 —— 合并 verdict、写入数据库、打印摘要。"""
import json

from src.models import (
    AlignmentDict, EntryDict, FuzzyResultsMap, GlossaryDict, PipelineContext,
    VerdictDict, VERDICT_FAIL, VERDICT_REVIEW, VERDICT_SUGGEST,
)
from src.reporting.report_generator import ReportGenerator
from src.storage.database import PipelineDB


def run_phase4(ctx: PipelineContext) -> None:
    print("[Phase 4] 报告生成...")

    rg = ReportGenerator()
    rg.load_alignment(ctx.alignment)
    rg.collect(ctx.format_verdicts, ctx.term_verdicts, ctx.llm_verdicts)

    report = rg.build_report()
    verdicts: list[VerdictDict] = report.get("verdicts", [])
    stats = report.get("stats", {})

    db = PipelineDB(ctx.output_dir / "pipeline.db")
    db.save_verdicts(verdicts, "merged")
    db.set_meta("stats", json.dumps(stats, ensure_ascii=False))
    db.close()

    print(f"  审校报告 → {ctx.output_dir / 'pipeline.db'} (verdicts 表)")
    rg.print_summary()
    rg.print_verdict_table()
