"""LLM 桥接器 —— 异步批处理审校、最终过滤、响应解析、交互模式。"""
import asyncio
import json
import re
import sys

from src import config as cfg
from src.models import (
    AutoVerdictsMap,
    EntryDict,
    FilterDiscardRecord,
    FuzzyResultsMap,
    GlossaryDict,
    LLMCallable,
    VerdictDict,
)
from src.llm.prompts import (
    build_filter_prompt,
    build_review_prompt,
    classify_key,
    merge_multipart_entries,
)


# ═══════════════════════════════════════════════════════════
# 响应解析器
# ═══════════════════════════════════════════════════════════

def parse_review_response(response: str) -> list[VerdictDict]:
    # 直接解析整个响应
    try:
        data = json.loads(response)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "verdicts" in data:
            return data["verdicts"]
    except json.JSONDecodeError:
        pass
    # 提取 JSON 数组
    json_match = re.search(r"\[.*\]", response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    # 逐行解析 JSON 对象
    results: list[dict[str, Any]] = []
    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                if "key" in obj and "verdict" in obj:
                    results.append(obj)
            except json.JSONDecodeError:
                continue
    return results


# ═══════════════════════════════════════════════════════════
# LLM 桥接器
# ═══════════════════════════════════════════════════════════

class LLMBridge:

    def __init__(
        self,
        llm_call: LLMCallable | None = None,
        filter_llm_call: LLMCallable | None = None,
    ):
        self.llm_call = llm_call
        self.filter_llm_call = filter_llm_call

    # ── 批量审校 ──────────────────────────────────────

    def review_batch(
        self,
        entries: list[EntryDict],
        glossary_entries: list[GlossaryDict] | None = None,
        auto_verdicts_map: AutoVerdictsMap | None = None,
        fuzzy_results_map: FuzzyResultsMap | None = None,
        batch_size: int = 20,
        max_workers: int | None = None,
    ) -> list[VerdictDict]:
        if not self.llm_call:
            raise RuntimeError("LLMBridge 未配置 llm_call 函数")
        if max_workers is None:
            max_workers = cfg.MAX_WORKERS
        merged = merge_multipart_entries(entries)
        prompts = build_review_prompt(
            entries, glossary_entries, auto_verdicts_map,
            fuzzy_results_map, batch_size, merged_context=merged,
        )

        async def _run_all() -> list[dict[str, Any]]:
            sem = asyncio.Semaphore(max_workers)

            async def _process(i: int, prompt: str) -> list[dict[str, Any]]:
                async with sem:
                    try:
                        loop = asyncio.get_running_loop()
                        response = await loop.run_in_executor(None, self.llm_call, prompt)
                        parsed = parse_review_response(response)
                        print(f"  [LLM] 批次 {i+1}/{len(prompts)} ({len(prompt)//4} tokens) → {len(parsed)} verdicts",
                              file=sys.stderr)
                        for v in parsed:
                            v.setdefault("source", "llm_review")
                            v.setdefault("en_current", "")
                            v.setdefault("zh_current", "")
                            v.setdefault("suggestion", "")
                            v.setdefault("reason", "")
                        return parsed
                    except Exception as e:
                        print(f"  [LLM] 批次 {i+1}/{len(prompts)} ✗ {e}", file=sys.stderr)
                        return [{
                            "key": "", "en_current": "", "zh_current": "",
                            "verdict": "🔶 REVIEW", "suggestion": "",
                            "reason": f"LLM调用失败: {e}", "source": "llm_error",
                        }]

            tasks = [_process(i, p) for i, p in enumerate(prompts)]
            results: list[dict[str, Any]] = []
            for coro in asyncio.as_completed(tasks):
                results.extend(await coro)
            return results

        return asyncio.run(_run_all())

    # ── 最终过滤 ──────────────────────────────────────

    def filter_verdicts(
        self,
        verdicts: list[VerdictDict],
        batch_size: int | None = None,
        max_workers: int | None = None,
    ) -> tuple[list[VerdictDict], list[FilterDiscardRecord]]:
        _call = self.filter_llm_call or self.llm_call
        if not _call:
            return verdicts, []
        if batch_size is None:
            batch_size = cfg.FILTER_BATCH_SIZE
        if max_workers is None:
            max_workers = cfg.MAX_WORKERS
        prompts = build_filter_prompt(verdicts, batch_size)
        print(f"[Phase 5] 最终过滤: {len(verdicts)} 条 verdict → {len(prompts)} 批", file=sys.stderr)

        async def _run_all() -> tuple[set[str], list[FilterDiscardRecord], dict[str, str]]:
            sem = asyncio.Semaphore(max_workers)
            discarded_keys: set[str] = set()
            discard_records: list[FilterDiscardRecord] = []
            cleaned_reasons: dict[str, str] = {}

            async def _process(i: int, prompt: str) -> tuple[set[str], list[FilterDiscardRecord], dict[str, str]]:
                async with sem:
                    try:
                        loop = asyncio.get_running_loop()
                        response = await loop.run_in_executor(None, _call, prompt)
                        parsed = parse_review_response(response)
                        local_keys: set[str] = set()
                        local_records: list[FilterDiscardRecord] = []
                        local_reasons: dict[str, str] = {}
                        for item in parsed:
                            k = item.get("key", "").strip()
                            if not k:
                                continue
                            vd = item.get("verdict", "").strip()
                            if vd == "PASS":
                                local_keys.add(k)
                                local_records.append({"key": k, "reason": item.get("reason", "").strip()})
                                print(f"  [Filter] 驳回: {k} — {item.get('reason', '')}", file=sys.stderr)
                            elif vd != "PASS":
                                r = item.get("reason", "").strip()
                                if r:
                                    local_reasons[k] = r
                        print(f"  [Filter] 批次 {i+1}/{len(prompts)} → 驳回 {len(local_keys)} 条, 清洗 {len(local_reasons)} 条",
                              file=sys.stderr)
                        return local_keys, local_records, local_reasons
                    except Exception as e:
                        print(f"  [Filter] 批次 {i+1}/{len(prompts)} ✗ {e}", file=sys.stderr)
                        return set(), [], {}

            tasks = [_process(i, p) for i, p in enumerate(prompts)]
            for coro in asyncio.as_completed(tasks):
                keys, records, reasons = await coro
                discarded_keys.update(keys)
                discard_records.extend(records)
                cleaned_reasons.update(reasons)
            return discarded_keys, discard_records, cleaned_reasons

        discarded, discard_records, cleaned_reasons = asyncio.run(_run_all())
        print(f"  最终驳回: {len(discarded)} 条, 清洗 reason: {len(cleaned_reasons)} 条", file=sys.stderr)
        filtered = [v for v in verdicts if v.get("key") not in discarded]
        for v in filtered:
            k = v.get("key", "")
            if k in cleaned_reasons:
                v["reason"] = cleaned_reasons[k]
        return filtered, discard_records


# ═══════════════════════════════════════════════════════════
# 交互审校
# ═══════════════════════════════════════════════════════════

def interactive_entry_review(
    entries: list[EntryDict],
    auto_verdicts_map: AutoVerdictsMap | None = None,
    fuzzy_results_map: FuzzyResultsMap | None = None,
) -> list[VerdictDict]:
    verdicts: list[dict[str, Any]] = []
    options = {
        "1": ("PASS", ""),
        "2": ("⚠️ SUGGEST", ""),
        "3": ("❌ FAIL", ""),
        "4": ("🔶 REVIEW", ""),
    }
    for i, entry in enumerate(entries):
        key = entry["key"]
        en = entry.get("en", "")
        zh = entry.get("zh", "")
        cat = classify_key(key)
        print(f"\n--- [{i+1}/{len(entries)}] [{cat}] {key} ---")
        print(f'EN: "{en[:200]}"')
        print(f'ZH: "{zh[:200]}"')
        auto_v = (auto_verdicts_map or {}).get(key, [])
        for v in auto_v:
            print(f"  ⚙️ {v['verdict']}: {v['reason']}")
        fuzzy_r = (fuzzy_results_map or {}).get(key, [])
        for fr in fuzzy_r[:2]:
            print(f"  🔍 sim={fr['similarity']}% ZH: \"{fr['zh'][:80]}\"")
        print("判定: [1]PASS [2]SUGGEST [3]FAIL [4]REVIEW [s]skip")
        choice = input("> ").strip()
        if choice in options:
            verdict, _ = options[choice]
            suggestion = ""
            reason = ""
            if verdict != "PASS":
                reason = input("理由: ").strip()
                if verdict in ("⚠️ SUGGEST", "❌ FAIL"):
                    suggestion = input("建议译文: ").strip()
            verdicts.append({
                "key": key, "en_current": en, "zh_current": zh,
                "verdict": verdict, "suggestion": suggestion,
                "reason": reason, "source": "interactive",
            })
        else:
            print("跳过")
    return verdicts
