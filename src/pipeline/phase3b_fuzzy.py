"""Phase 3b: 模糊搜索相似的现有译文条目。"""
import json

from src.models import EntryDict, FuzzyResultDict, FuzzyResultsMap, PipelineContext
from src.tools.fuzzy_search import fuzzy_search_lines


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
    if ctx.fuzzy_results_map:
        _save_json(ctx.output_dir / "04_fuzzy_results.json", ctx.fuzzy_results_map)


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
