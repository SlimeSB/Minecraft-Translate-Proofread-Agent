"""Phase 4: 报告生成 —— 合并 verdict、生成 JSON/Markdown、按 namespace 拆分。"""
import json
from typing import Any

from src.models import PipelineContext
from src.reporting.report_generator import ReportGenerator


def run_phase4(ctx: PipelineContext) -> None:
    print("[Phase 4] 报告生成...")

    rg = ReportGenerator()
    rg.load_alignment(ctx.alignment)
    rg.collect(ctx.format_verdicts, ctx.term_verdicts, ctx.llm_verdicts)

    review_path = ctx.output_dir / "06_review_report.json"
    rg.generate_review_report(str(review_path))
    rg.generate_markdown_report(str(ctx.output_dir / "report.md"))

    # ── 按 namespace 拆分 ──
    ns_map: dict[str, list[dict[str, Any]]] = {}
    for v in rg.verdicts:
        matched = next((e for e in ctx.alignment.get("matched_entries", [])
                        if e["key"] == v.get("key")), None)
        if not matched:
            continue
        ns = matched.get("namespace") or v.get("namespace", "")
        if ns:
            ns_map.setdefault(ns, []).append(v)

    if ns_map:
        ns_dir = ctx.output_dir / "namespaces"
        ns_dir.mkdir(parents=True, exist_ok=True)
        for ns, verdicts in ns_map.items():
            ns_keys = {e["key"] for e in ctx.alignment.get("matched_entries", [])
                       if e.get("namespace") == ns}

            ns_rg = ReportGenerator()
            ns_rg.alignment = ctx.alignment
            ns_rg.matched_entries = [e for e in ctx.alignment.get("matched_entries", [])
                                     if e.get("namespace") == ns]
            ns_rg.verdicts = verdicts
            ns_rg.compute_stats()

            ns_path = ns_dir / ns
            ns_path.mkdir(parents=True, exist_ok=True)

            ns_rg.generate_review_report(str(ns_path / "06_review_report.json"))
            ns_rg.generate_markdown_report(str(ns_path / "report.md"), ns)

            _save_json(ns_path / "02_terminology_glossary.json", ctx.glossary)

            ns_fmt_v = [v for v in ctx.format_verdicts if v.get("key") in ns_keys]
            _save_json(ns_path / "03_format_verdicts.json", {
                "total_checked": len(ns_rg.matched_entries),
                "issues_found": len(ns_fmt_v),
                "verdicts": ns_fmt_v,
            })

            ns_fuzzy = {k: v for k, v in ctx.fuzzy_results_map.items() if k in ns_keys}
            if ns_fuzzy:
                _save_json(ns_path / "04_fuzzy_results.json", ns_fuzzy)

            ns_llm_v = [v for v in ctx.llm_verdicts if v.get("key") in ns_keys]
            if ns_llm_v:
                _save_json(ns_path / "05_llm_verdicts.json", ns_llm_v)

        print(f"  按 namespace 拆分: {len(ns_map)} 组 → {ns_dir}")

    print(f"  审校报告: {review_path}")
    rg.print_summary()
    rg.print_verdict_table()


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
