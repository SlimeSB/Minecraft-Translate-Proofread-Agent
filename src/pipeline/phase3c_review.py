"""Phase 3c: LLM 审校 —— 筛选条目 → 模糊搜索 → 审校（/交互/干运行）。"""
import json

from src.logging import info
from src.models import (
    EntryDict, PipelineContext, SOURCE_UNTRANSLATED_REVIEW, VerdictDict,
    update_diagnosis, verdict_str_to_int, verdict_int_to_str,
)
from src.llm.prompts import filter_for_llm, build_review_prompt, merge_multipart_entries, is_manual_format, manual_format_label
from src.llm.bridge import LLMBridge, interactive_entry_review
from src.pipeline.phase3b_fuzzy import run_phase3b
from src import config as cfg


def _load_glossary(ctx: PipelineContext) -> list:
    """加载术语表：优先从 output_dir/glossary.json 读取，不存在则 fallback ctx.glossary。"""
    glossary_path = ctx.output_dir / "glossary.json"
    if glossary_path.exists():
        with open(glossary_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return ctx.glossary


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
            "source": SOURCE_UNTRANSLATED_REVIEW,
        })
    return results


def _filter_and_prepare(ctx: PipelineContext, glossary: list) -> tuple[list[EntryDict], list[EntryDict], int]:
    """筛选需 LLM 审校的条目并运行 Phase 3b 模糊搜索。
    返回 (llm_entries, untranslated_llm, auto_pass_count)。"""
    matched = ctx.alignment.get("matched_entries", [])

    untranslated_keys: set[str] = set()
    db = ctx.db
    rows = db.execute(
        "SELECT key FROM entries WHERE diagnoses LIKE '%untranslated_review%'"
    ).fetchall()
    untranslated_keys = {r["key"] for r in rows}

    llm_entries, auto_pass = filter_for_llm(matched, glossary)

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

    if llm_entries or untranslated_llm:
        run_phase3b(ctx, llm_entries + untranslated_llm)

    return llm_entries, untranslated_llm, len(auto_pass)


def _review_entries(
    ctx: PipelineContext,
    llm_entries: list[EntryDict],
    untranslated_llm: list[EntryDict],
    glossary: list,
) -> list[VerdictDict]:
    """执行主线审校与未翻译队列审校，返回 verdicts。"""
    verdicts: list[VerdictDict] = []
    auto_map = ctx.auto_verdicts_map()

    review_batch_size = ctx.batch_size or cfg.get("review_batch_size", 25)

    if llm_entries:
        if ctx.dry_run:
            merged = merge_multipart_entries(llm_entries)
            prompts = build_review_prompt(
                llm_entries, glossary, auto_map,
                ctx.fuzzy_results_map, review_batch_size, merged_context=merged,
                dict_stores=ctx.dict_stores,
            )
            total_chars = sum(len(p) for p in prompts)
            info(f"  [DRY RUN] {len(prompts)} 批, ~{total_chars//4} tokens")
            manual_count = sum(1 for e in llm_entries if is_manual_format(e["key"]))
            info(f"    普通条目: {len(llm_entries) - manual_count} 条, 手册条目: {manual_count} 条")
        elif ctx.interactive:
            info("  进入交互审校模式...")
            verdicts = interactive_entry_review(
                llm_entries, auto_map, ctx.fuzzy_results_map,
            )
        elif ctx.llm_call and not ctx.no_llm:
            bridge = LLMBridge(ctx.llm_call)
            verdicts = bridge.review_batch(
                llm_entries, glossary, auto_map,
                ctx.fuzzy_results_map, review_batch_size,
                dict_stores=ctx.dict_stores,
            )

    if untranslated_llm:
        untranslated_verdicts: list[VerdictDict] = []
        if ctx.dry_run:
            prompts = build_review_prompt(
                untranslated_llm, glossary, auto_map,
                ctx.fuzzy_results_map, 1, merged_context=None,
                dict_stores=ctx.dict_stores,
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
        verdicts.extend(untranslated_verdicts)

    return verdicts


def run_phase3c(ctx: PipelineContext) -> None:
    glossary = _load_glossary(ctx)
    llm_entries, untranslated_llm, _auto_pass = _filter_and_prepare(ctx, glossary)

    if not llm_entries and not untranslated_llm:
        db = ctx.db
        db.execute("UPDATE entries SET state=2 WHERE state < 2")
        db.commit()
        return

    llm_verdicts = _review_entries(ctx, llm_entries, untranslated_llm, glossary)
    info(f"  LLM verdicts: {len(llm_verdicts)} 条")

    db = ctx.db
    source = "llm_review"

    # 8.1: Write LLM verdicts directly to entries table
    for v in llm_verdicts:
        key = v.get("key", "")
        if not key:
            continue
        llm_verdict_str = v.get("verdict", "PASS")
        verdict_int = verdict_str_to_int(llm_verdict_str)
        suggestion = v.get("suggestion", "")
        reason = v.get("reason", "")
        src = v.get("source", source)

        diagnoses_json = update_diagnosis(db, key, src, reason)
        db.execute(
            "UPDATE entries SET state=MAX(state,2), verdict=MAX(verdict,?), suggestion=?, diagnoses=? WHERE key=?",
            (verdict_int, suggestion, diagnoses_json, key))

    # 8.2: Blanket push all entries to state >= 2
    db.execute("UPDATE entries SET state=2 WHERE state < 2")
    db.commit()
