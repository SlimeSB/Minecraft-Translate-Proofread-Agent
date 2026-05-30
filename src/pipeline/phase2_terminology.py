"""Phase 2: 术语提取、归并、一致性检查。"""
import json

from src import config as cfg
from src.logging import info
from src.llm.prompts import is_excluded_from_terminology
from src.models import (
    GlossaryDict, PipelineContext, VerdictDict,
    update_diagnosis, verdict_str_to_int,
)
from src.checkers.terminology_builder import TerminologyBuilder, llm_verify_glossary, check_consistency
from src.dictionary.protocol import SHORT, collect_hints


def run_phase2(ctx: PipelineContext) -> None:
    info("[Phase 2] 术语提取与一致性检查...")

    if ctx.pr_mode and ctx.pr_version_groups:
        lang_en: dict[str, str] = {}
        lang_zh: dict[str, str] = {}
        for slug, g in ctx.pr_version_groups.items():
            for ver, vd in g["version_data"].items():
                for raw_key, en_val in vd["full_en"].items():
                    if not is_excluded_from_terminology(raw_key):
                        lang_en[raw_key] = en_val
                for raw_key, zh_val in vd["full_zh"].items():
                    if not is_excluded_from_terminology(raw_key):
                        lang_zh[raw_key] = zh_val
    elif ctx.pr_mode and ctx.pr_full_en_data:
        lang_en = {k: v for k, v in ctx.pr_full_en_data.items() if not is_excluded_from_terminology(k)}
        lang_zh = {k: v for k, v in ctx.pr_full_zh_data.items() if not is_excluded_from_terminology(k)}
    else:
        lang_en = {k: v for k, v in ctx.en_data.items() if not is_excluded_from_terminology(k)}
        lang_zh = {k: v for k, v in ctx.zh_data.items() if not is_excluded_from_terminology(k)}

    tb = TerminologyBuilder()
    tb.load(lang_en, lang_zh, ctx.alignment)
    tb.extract(min_freq=cfg.TERM_MIN_FREQ, max_ngram=cfg.TERM_MAX_NGRAM)
    info(f"  [术语提取] unigrams={len(tb.extracted.get('unigrams',[]))}, "
         f"bigrams={len(tb.extracted.get('bigrams',[]))}, "
         f"trigrams={len(tb.extracted.get('trigrams',[]))}")
    tb.merge_lemmas()
    # dump bucket size distribution
    sizes = sorted([len(v["keys"]) for v in tb.merged.values()], reverse=True)
    if sizes:
        info(f"  [术语归并] bucket keys 分布: max={sizes[0]}, "
             f"p90={sizes[len(sizes)//10] if len(sizes)>=10 else sizes[-1]}, "
             f"median={sizes[len(sizes)//2]}, min={sizes[-1]}, "
             f">=3 keys={sum(1 for s in sizes if s>=3)}")
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
    term_verdicts = check_consistency(ctx.glossary, tb.matched_entries, tb.merged)

    info(f"  术语表: {len(ctx.glossary)} 条")
    info(f"  术语不一致 verdicts: {len(term_verdicts)} 条")

    # 5.1: Write glossary to output_dir/glossary.json
    glossary_path = ctx.output_dir / "glossary.json"
    with open(glossary_path, "w", encoding="utf-8") as f:
        json.dump(ctx.glossary, f, ensure_ascii=False, indent=2)
    info(f"  术语表已写入: {glossary_path}")

    # 5.2: Write verdicts directly to entries table
    db = ctx.db
    source = "terminology_check"
    for v in term_verdicts:
        key = v.get("key", "")
        if not key:
            continue
        checker_verdict = v.get("verdict", "PASS")
        verdict_int = verdict_str_to_int(checker_verdict)
        reason = v.get("reason", "")

        diagnoses_json = update_diagnosis(db, key, source, reason)
        db.execute(
            "UPDATE entries SET state=MAX(state,1), verdict=MAX(verdict,?), diagnoses=? WHERE key=?",
            (verdict_int, diagnoses_json, key))

    # 5.3: Blanket push all entries to state >= 1
    db.execute("UPDATE entries SET state=MAX(state,1)")
    db.commit()
