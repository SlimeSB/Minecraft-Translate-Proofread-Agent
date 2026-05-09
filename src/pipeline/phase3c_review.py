"""Phase 3c: LLM 审校 —— 筛选条目 → 模糊搜索 → 审校（/交互/干运行）。"""
from src.logging import info
from src.models import EntryDict, PipelineContext, VerdictDict
from src.llm.prompts import classify_entries, filter_for_llm, build_review_prompt, merge_multipart_entries
from src.llm.bridge import LLMBridge, interactive_entry_review
from src.pipeline.phase3b_fuzzy import run_phase3b
from src.storage.database import PipelineDB
from src import config as cfg


def _collect_status_verdicts(untranslated_entries: list[EntryDict]) -> list[VerdictDict]:
    """仅适用于没有 LLM call 时的降级路径。"""
    results: list[VerdictDict] = []
    for e in untranslated_entries:
        results.append({
            "key": e["key"],
            "en_current": e.get("en", ""),
            "zh_current": e.get("zh", ""),
            "verdict": "🔶 REVIEW",
            "suggestion": "",
            "reason": "疑似未翻译（值相同，需人工判断）",
            "source": "untranslated_review",
        })
    return results


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

    # 分离未翻译条目为独立队列
    untranslated_llm: list[EntryDict] = []
    if untranslated_keys:
        keep: list[EntryDict] = []
        for e in llm_entries:
            if e["key"] in untranslated_keys:
                untranslated_llm.append(e)
            else:
                keep.append(e)
        if untranslated_llm:
            llm_entries = keep

    info(f"[Phase 3c] LLM审校: 总{len(matched)}条 → 自动通过{len(auto_pass)}条, "
          f"需审校{len(llm_entries)}条, 未翻译队列{len(untranslated_llm)}条")

    if not llm_entries and not untranslated_llm:
        ctx.llm_verdicts = []
        return

    # Phase 3b: 模糊搜索（对触发模式的条目）
    all_candidates = llm_entries + untranslated_llm
    run_phase3b(ctx, all_candidates)

    auto_map = ctx.auto_verdicts_map()
    ctx.llm_verdicts = []

    # ── 主线审校 ──
    if llm_entries:
        review_batch_size = ctx.batch_size or cfg.get("review_batch_size", 25)  # Double fallback; ctx.batch_size already carries PipelineContext default
        if ctx.dry_run:
            merged = merge_multipart_entries(llm_entries)
            prompts = build_review_prompt(
                llm_entries, ctx.glossary, auto_map,
                ctx.fuzzy_results_map, review_batch_size, merged_context=merged,
                external_dict_store=ctx.external_dict_store,
            )
            total_chars = sum(len(p) for p in prompts)
            info(f"  [DRY RUN] {len(prompts)} 批, ~{total_chars//4} tokens")
            groups = classify_entries(llm_entries)
            for cat, entries in sorted(groups.items()):
                info(f"    {cat}: {len(entries)} 条")
        elif ctx.interactive:
            info("  进入交互审校模式...")
            ctx.llm_verdicts = interactive_entry_review(
                llm_entries, auto_map, ctx.fuzzy_results_map,
            )
        elif ctx.llm_call and not ctx.no_llm:
            bridge = LLMBridge(ctx.llm_call)
            ctx.llm_verdicts = bridge.review_batch(
                llm_entries, ctx.glossary, auto_map,
                ctx.fuzzy_results_map, review_batch_size,
                external_dict_store=ctx.external_dict_store,
            )

    # ── 未翻译队列审校 ──
    if untranslated_llm:
        untranslated_verdicts: list[VerdictDict] = []
        if ctx.dry_run:
            prompts = build_review_prompt(
                untranslated_llm, ctx.glossary, auto_map,
                ctx.fuzzy_results_map, 1, merged_context=None,
                external_dict_store=ctx.external_dict_store,
            )
            total_chars = sum(len(p) for p in prompts)
            info(f"  [未翻译-干运行] {len(untranslated_llm)} 条, ~{total_chars//4} tokens")
        elif ctx.interactive:
            info("  [未翻译] 进入交互审校模式...")
            untranslated_verdicts = interactive_entry_review(
                untranslated_llm, auto_map, ctx.fuzzy_results_map,
            )
        elif ctx.llm_call and not ctx.no_llm:
            bridge = LLMBridge(ctx.llm_call)
            untranslated_verdicts = bridge.review_untranslated(untranslated_llm, batch_size=review_batch_size)
        else:
            untranslated_verdicts = _collect_status_verdicts(untranslated_llm)

        if untranslated_verdicts:
            info(f"  [未翻译] {len(untranslated_verdicts)} 条 verdicts")
        ctx.llm_verdicts.extend(untranslated_verdicts)

    # ── --no-llm 降级 ──
    if not ctx.llm_call or ctx.no_llm:
        ctx.llm_verdicts += [
            v for v in ctx.format_verdicts + ctx.term_verdicts
            if v.get("verdict") != "PASS"
        ]

    info(f"  LLM verdicts: {len(ctx.llm_verdicts)} 条")

    with PipelineDB(ctx.output_dir / "pipeline.db") as db:
        db.save_verdicts(ctx.llm_verdicts, "llm")  # type: ignore[arg-type]
