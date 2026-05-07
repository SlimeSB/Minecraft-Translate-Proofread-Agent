"""Phase 3b: 模糊搜索相似的现有译文条目。"""
from src.models import EntryDict, FuzzyResultDict, FuzzyResultsMap, PipelineContext
from src.tools.fuzzy_search import fuzzy_search_lines
from src.storage.database import PipelineDB


def run_phase3b(ctx: PipelineContext, llm_entries: list[EntryDict]) -> None:
    print("[Phase 3b] 模糊搜索...")
    fuzzy_trigger_patterns = [".desc", "death.attack.", "advancements."]
    to_search: list[EntryDict] = [
        e for e in llm_entries
        if any(p in e["key"] for p in fuzzy_trigger_patterns)
    ]

    ctx.fuzzy_results_map = {}
    for entry in to_search:
        key = entry["key"]
        en = entry.get("en", "")
        if not en or not isinstance(en, str):
            continue
        results = fuzzy_search_lines(
            query=en,
            en_entries=ctx.en_data,
            zh_entries=ctx.zh_data,
            top_n=ctx.fuzzy_top,
            threshold=ctx.fuzzy_threshold,
        )
        results = [r for r in results if r.get("key") != key]
        if results:
            ctx.fuzzy_results_map[key] = results

    print(f"  模糊搜索: {len(to_search)} 条查询, {len(ctx.fuzzy_results_map)} 条有结果")

    db = PipelineDB(ctx.output_dir / "pipeline.db")
    db.save_fuzzy_results(ctx.fuzzy_results_map)
    db.close()
