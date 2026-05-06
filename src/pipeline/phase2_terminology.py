"""Phase 2: 术语提取、归并、一致性检查。"""
import json

from src.models import GlossaryDict, PipelineContext, VerdictDict
from src.checkers.terminology_builder import TerminologyBuilder


def run_phase2(ctx: PipelineContext) -> None:
    print("[Phase 2] 术语提取与一致性检查...")

    # GuideME 条目不参与术语提取
    lang_en = {k: v for k, v in ctx.en_data.items() if not k.startswith("ae2guide:")}
    lang_zh = {k: v for k, v in ctx.zh_data.items() if not k.startswith("ae2guide:")}

    tb = TerminologyBuilder(cache_path="lemma_cache.json")
    tb.load(lang_en, lang_zh, ctx.alignment)
    tb.extract(min_freq=2, max_ngram=3)
    tb.merge_lemmas(llm_call=ctx.llm_call)
    ctx.glossary = tb.build_glossary()
    ctx.term_verdicts = tb.check_consistency()

    print(f"  术语表: {len(ctx.glossary)} 条")
    print(f"  术语不一致 verdicts: {len(ctx.term_verdicts)} 条")

    _save_json(ctx.output_dir / "02_terminology_glossary.json", ctx.glossary)


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {path}")
