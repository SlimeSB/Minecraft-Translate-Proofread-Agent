"""Phase 2: 术语提取、归并、一致性检查。"""
from src import config as cfg
from src.logging import info
from src.models import GlossaryDict, PipelineContext, VerdictDict
from src.checkers.terminology_builder import TerminologyBuilder, llm_verify_glossary, check_consistency
from src.dictionary.protocol import LookupMode
from src.storage.database import PipelineDB


def run_phase2(ctx: PipelineContext) -> None:
    info("[Phase 2] 术语提取与一致性检查...")

    # GuideME 条目不参与术语提取
    if ctx.pr_mode and ctx.pr_full_en_data:
        lang_en = {k: v for k, v in ctx.pr_full_en_data.items() if not k.startswith(cfg.GUIDEME_PREFIX)}
        lang_zh = {k: v for k, v in ctx.pr_full_zh_data.items() if not k.startswith(cfg.GUIDEME_PREFIX)}
    else:
        lang_en = {k: v for k, v in ctx.en_data.items() if not k.startswith(cfg.GUIDEME_PREFIX)}
        lang_zh = {k: v for k, v in ctx.zh_data.items() if not k.startswith(cfg.GUIDEME_PREFIX)}

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
                parts: list[str] = []
                for store in ctx.dict_stores:
                    try:
                        hint = store.lookup(en_term, mode=LookupMode.SHORT)
                        if hint:
                            parts.append(hint)
                    except Exception:
                        pass
                if parts:
                    term_hints[en_term] = "\n".join(parts)
        ctx.glossary = llm_verify_glossary(ctx.glossary, tb.en_data, tb.zh_data, ctx.llm_call, term_hints=term_hints)
    ctx.term_verdicts = check_consistency(ctx.glossary, tb.matched_entries, tb.merged)

    info(f"  术语表: {len(ctx.glossary)} 条")
    info(f"  术语不一致 verdicts: {len(ctx.term_verdicts)} 条")

    with PipelineDB(ctx.output_dir / "pipeline.db") as db:
        db.save_glossary(ctx.glossary)
        db.save_verdicts(ctx.term_verdicts, "terminology")
