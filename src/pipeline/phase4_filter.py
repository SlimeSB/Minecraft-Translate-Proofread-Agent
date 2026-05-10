"""Phase 4: 最终 LLM 过滤。

从 pipeline.db 读取合并后的判决，查过滤缓存，对未命中条目调 LLM，
结果写回 DB（驳回 → 改判为 PASS；保留 → 维持原 verdict）。
"""
import json
from collections.abc import Mapping
from typing import Any

from src.logging import info
from src.models import (
    FilterDiscardRecord, PipelineContext, VerdictDict,
)
from src.llm.bridge import LLMBridge
from src.storage.database import PipelineDB


def run_phase4(ctx: PipelineContext) -> None:
    if not ctx.llm_call or ctx.no_llm or ctx.dry_run:
        return

    info("[Phase 4] 最终 LLM 过滤...")
    with PipelineDB(ctx.output_dir / "pipeline.db") as db:
        verdicts: list[VerdictDict] = db.load_verdicts(phase="merged", filtered=0)  # type: ignore[assignment]
        if not verdicts:
            info("  无 verdict 需要过滤")
            return

        cached_pass_keys: set[str] = set()
        cached_clean_reasons: dict[str, str] = {}
        uncached: list[VerdictDict] = []

        for v in verdicts:
            ck = _cache_key(v)
            result = db.lookup_filter_cache(ck)
            if result is not None:
                action, cleaned = result
                if action == "PASS":
                    cached_pass_keys.add(v["key"])
                elif cleaned:
                    cached_clean_reasons[v["key"]] = cleaned
            else:
                uncached.append(v)

        cache_hits = len(verdicts) - len(uncached)
        info(f"  缓存: {db.filter_cache_size()} 条, 命中 {cache_hits}, 需LLM {len(uncached)}")
        ctx.filter_cache_hits = cache_hits
        ctx.filter_cache_total = len(verdicts)

        bridge = LLMBridge(ctx.llm_call, filter_llm_call=ctx.filter_llm_call)

        if uncached:
            filtered_uncached, passes_uncached = bridge.filter_verdicts(uncached)

            pass_keys: set[str] = {d["key"] for d in passes_uncached}
            uncached_reasons: dict[str, str] = {}
            for v in filtered_uncached:
                k = v["key"]
                r = v.get("reason", "")
                if r and k not in uncached_pass:
                    uncached_reasons[k] = r

            for v in uncached:
                ck = _cache_key(v)
                k = v["key"]
                if k in pass_keys:
                    db.store_filter_cache(ck, "PASS", "")
                else:
                    db.store_filter_cache(ck, "KEEP", uncached_reasons.get(k, ""))
            db.commit_filter_cache()
        else:
            pass_keys = set()
            uncached_reasons = {}

        all_pass = cached_pass_keys | pass_keys
        all_reasons = {**cached_clean_reasons, **uncached_reasons}

        for v in verdicts:
            k = v["key"]
            if k in all_pass:
                db.set_filtered(k, "PASS", "")
            else:
                if k in all_reasons:
                    v["reason"] = all_reasons[k]
                db.set_filtered(k, v.get("verdict", ""), v.get("reason", ""))

        removed = len(all_pass)
        kept = len(verdicts) - removed
        info(f"  驳回(PASS) {removed} 条, 保留 {kept} 条")

        stats = db.get_merged_stats()
        db.set_meta("filtered_stats", json.dumps(stats, ensure_ascii=False))


def _cache_key(v: Mapping[str, Any]) -> str:
    import hashlib
    raw = ":".join([
        v.get("key", ""),
        v.get("verdict", ""),
        v.get("zh_current", "")[:150],
        v.get("reason", "")[:200],
    ])
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=16).hexdigest()
