"""Phase 2: 术语提取、归并、一致性检查。"""
from src import config as cfg
from src.logging import info
from src.llm.prompts import is_excluded_from_terminology
from src.models import GlossaryDict, PHASE_TERMINOLOGY, PipelineContext, VerdictDict
from src.checkers.terminology_builder import TerminologyBuilder, llm_verify_glossary, check_consistency
from src.dictionary.protocol import SHORT, collect_hints
from src.storage.database import PipelineDB


def run_phase2(ctx: PipelineContext) -> None:
    info("[Phase 2] 术语提取与一致性检查...")

    if ctx.pr_mode and ctx.pr_version_groups:
        lang_en: dict[str, str] = {}
        lang_zh: dict[str, str] = {}
        for slug, g in ctx.pr_version_groups.items():
            for ver, vd in g["version_data"].items():
                for raw_key, en_val in vd["full_en"].items():
                    if not is_excluded_from_terminology(raw_key):
                        composite_key = f"{slug}/{ver}/{raw_key}"
                        lang_en[composite_key] = en_val
                for raw_key, zh_val in vd["full_zh"].items():
                    if not is_excluded_from_terminology(raw_key):
                        composite_key = f"{slug}/{ver}/{raw_key}"
                        lang_zh[composite_key] = zh_val
    elif ctx.pr_mode and ctx.pr_full_en_data:
        lang_en = {k: v for k, v in ctx.pr_full_en_data.items() if not is_excluded_from_terminology(k)}
        lang_zh = {k: v for k, v in ctx.pr_full_zh_data.items() if not is_excluded_from_terminology(k)}
    else:
        lang_en = {k: v for k, v in ctx.en_data.items() if not is_excluded_from_terminology(k)}
        lang_zh = {k: v for k, v in ctx.zh_data.items() if not is_excluded_from_terminology(k)}

    tb = TerminologyBuilder()
    tb.load(lang_en, lang_zh, ctx.alignment)
    tb.extract(min_freq=cfg.TERM_MIN_FREQ, max_ngram=cfg.TERM_MAX_NGRAM)
    tb.merge_lemmas(llm_call=ctx.llm_call)
    ctx.glossary = tb.build_glossary()
    if ctx.llm_call and not ctx.no_llm:
        term_hints: dict[str, str] | None = None
        if ctx.dict_stores:
            term_hints = {}
            for g in ctx.glossary:
                en_term = g["en"].lower()
                hint = collect_hints(en_term, ctx.dict_stores, mode=SHORT)
                if hint:
                    term_hints[en_term] = hint
        ctx.glossary = llm_verify_glossary(ctx.glossary, tb.en_data, tb.zh_data, ctx.llm_call, term_hints=term_hints)
    ctx.term_verdicts = check_consistency(ctx.glossary, tb.matched_entries, tb.merged)

    info(f"  术语表: {len(ctx.glossary)} 条")
    info(f"  术语不一致 verdicts: {len(ctx.term_verdicts)} 条")

    with PipelineDB(ctx.output_dir / "pipeline.db") as db:
        db.save_glossary(ctx.glossary)
        db.save_verdicts(ctx.term_verdicts, PHASE_TERMINOLOGY)
