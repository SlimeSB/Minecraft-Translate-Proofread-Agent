"""Phase 2: 术语提取、归并、一致性检查。"""
from src.models import GlossaryDict, PipelineContext, VerdictDict
from src.checkers.terminology_builder import TerminologyBuilder
from src.storage.database import PipelineDB


def run_phase2(ctx: PipelineContext) -> None:
    print("[Phase 2] 术语提取与一致性检查...")

    # GuideME 条目不参与术语提取
    lang_en = {k: v for k, v in ctx.en_data.items() if not k.startswith("ae2guide:")}
    lang_zh = {k: v for k, v in ctx.zh_data.items() if not k.startswith("ae2guide:")}

    tb = TerminologyBuilder()
    tb.load(lang_en, lang_zh, ctx.alignment)
    tb.extract(min_freq=2, max_ngram=3)
    tb.merge_lemmas(llm_call=ctx.llm_call)
    ctx.glossary = tb.build_glossary()
    ctx.term_verdicts = tb.check_consistency()

    print(f"  术语表: {len(ctx.glossary)} 条")
    print(f"  术语不一致 verdicts: {len(ctx.term_verdicts)} 条")

    db = PipelineDB(ctx.output_dir / "pipeline.db")
    db.save_glossary(ctx.glossary)
    db.save_verdicts(ctx.term_verdicts, "terminology")
    db.close()
