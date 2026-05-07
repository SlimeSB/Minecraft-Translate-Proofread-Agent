"""Phase 3c: LLM 审校 —— 筛选条目 → 模糊搜索 → 审校（/交互/干运行）。"""
from src.models import EntryDict, PipelineContext, VerdictDict
from src.llm.prompts import classify_entries, filter_for_llm, build_review_prompt, merge_multipart_entries
from src.llm.bridge import LLMBridge, interactive_entry_review
from src.pipeline.phase3b_fuzzy import run_phase3b
from src.storage.database import PipelineDB


def run_phase3c(ctx: PipelineContext) -> None:
    matched = ctx.alignment.get("matched_entries", [])

    auto_flagged_keys: set[str] = set()
    for v in ctx.format_verdicts + ctx.term_verdicts:
        auto_flagged_keys.add(v.get("key", ""))

    untranslated_keys: set[str] = {
        v.get("key", "") for v in ctx.format_verdicts
        if "值相同" in v.get("reason", "")
    }

    llm_entries, auto_pass = filter_for_llm(matched, auto_flagged_keys, ctx.glossary)

    if untranslated_keys:
        before = len(llm_entries)
        llm_entries = [e for e in llm_entries if e["key"] not in untranslated_keys]
        if before != len(llm_entries):
            print(f"  跳过疑似未翻译: {before - len(llm_entries)} 条")

    print(f"[Phase 3c] LLM审校: 总{len(matched)}条 → 自动通过{len(auto_pass)}条, "
          f"需审校{len(llm_entries)}条")

    if not llm_entries:
        ctx.llm_verdicts = []
        return

    # Phase 3b: 模糊搜索（对触发模式的条目）
    run_phase3b(ctx, llm_entries)

    auto_map = ctx.auto_verdicts_map()

    if ctx.dry_run:
        merged = merge_multipart_entries(llm_entries)
        prompts = build_review_prompt(
            llm_entries, ctx.glossary, auto_map,
            ctx.fuzzy_results_map, ctx.batch_size, merged_context=merged,
            external_dict_store=ctx.external_dict_store,
        )
        total_chars = sum(len(p) for p in prompts)
        print(f"  [DRY RUN] {len(prompts)} 批, ~{total_chars//4} tokens")
        groups = classify_entries(llm_entries)
        for cat, entries in sorted(groups.items()):
            print(f"    {cat}: {len(entries)} 条")
        ctx.llm_verdicts = []
    elif ctx.interactive:
        print("  进入交互审校模式...")
        ctx.llm_verdicts = interactive_entry_review(
            llm_entries, auto_map, ctx.fuzzy_results_map,
        )
    elif ctx.llm_call and not ctx.no_llm:
        bridge = LLMBridge(ctx.llm_call)
        ctx.llm_verdicts = bridge.review_batch(
            llm_entries, ctx.glossary, auto_map,
            ctx.fuzzy_results_map, ctx.batch_size,
            external_dict_store=ctx.external_dict_store,
        )
    else:
        print("  跳过 LLM 审校 (--no-llm)")
        ctx.llm_verdicts = [
            v for v in ctx.format_verdicts + ctx.term_verdicts
            if v.get("verdict") != "PASS"
        ]

    print(f"  LLM verdicts: {len(ctx.llm_verdicts)} 条")

    db = PipelineDB(ctx.output_dir / "pipeline.db")
    db.save_verdicts(ctx.llm_verdicts, "llm")
    db.close()
