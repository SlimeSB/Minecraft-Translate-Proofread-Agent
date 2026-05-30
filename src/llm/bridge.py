"""LLM 桥接器 —— 异步批处理审校、最终过滤、响应解析、交互模式。"""
import asyncio
import json
import re
from src.logging import info, warn, debug

from src import config as cfg
from src.models import (
    AutoVerdictsMap,
    EntryDict,
    FilterDiscardRecord,
    FuzzyResultsMap,
    GlossaryDict,
    LLMCallable,
    SOURCE_INTERACTIVE,
    SOURCE_LLM_ERROR,
    SOURCE_LLM_REVIEW,
    SOURCE_UNTRANSLATED_REVIEW,
    VerdictDict,
    normalize_verdict,
)
from src.llm.prompts import (
    build_filter_prompt,
    build_review_prompt,
    build_untranslated_prompt,
    manual_format_label,
    merge_multipart_entries,
)


# ═══════════════════════════════════════════════════════════
# 响应解析器
# ═══════════════════════════════════════════════════════════

def _normalize_verdict(v: VerdictDict) -> None:
    """桥内规范化——委托给共享 normalize_verdict 再写回。"""
    nv = normalize_verdict(v, fields=("source", "en_current", "zh_current", "suggestion", "reason", "verdict", "key"))
    for k in ("source", "en_current", "zh_current", "suggestion", "reason", "verdict", "key"):
        v[k] = nv[k]


def _is_truncated_json(response: str) -> bool:
    """检测 JSON 响应是否被截断。"""
    stripped = response.strip()
    if not stripped:
        return False
    if stripped.count("{") != stripped.count("}"):
        return True
    if stripped.count("[") != stripped.count("]"):
        return True
    return False


def parse_llm_json(response: str, *, extract_code_block: bool = False) -> list[dict]:
    """统一 LLM JSON 响应解析（三层回退：直接→正则提取→逐行）。

    设 extract_code_block=True 时先剥离 markdown 围栏代码块。
    返回 dict 列表；解析失败返回空列表。
    """
    text = response.strip()
    if extract_code_block and "```" in text:
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "verdicts" in data:
            return data["verdicts"]
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"\[.*\]", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    results: list[dict] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                results.append(obj)
            except json.JSONDecodeError:
                continue
    return results


def parse_review_response(response: str) -> list[VerdictDict]:
    return parse_llm_json(response)


# ═══════════════════════════════════════════════════════════
# 共享异步 LLM 调用（semaphore + 重试 + HTML/截断守卫）
# ═══════════════════════════════════════════════════════════

async def _llm_call_with_retry(
    prompt: str,
    llm_call: LLMCallable,
    sem: asyncio.Semaphore,
    label: str,
    batch_idx: int,
    total_batches: int,
    max_retries: int,
) -> str:
    """共享异步 LLM 调用: semaphore 门控、指数退避重试、HTML/XML 响应守卫、截断 JSON 检测。
    返回原始响应字符串。最终失败时抛出 Exception。"""
    async with sem:
        for attempt in range(1, max_retries + 1):
            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(None, llm_call, prompt)
                if response.strip().startswith("<!") or response.strip().startswith("<html"):
                    raise RuntimeError(f"非 JSON 响应: {response[:100]}")
                parsed = parse_review_response(response)
                if _is_truncated_json(response) and not parsed:
                    warn(f"  [{label}] 批次 {batch_idx+1} JSON 截断, 重试第 {attempt} 次")
                    continue
                return response
            except Exception as e:
                if attempt == max_retries:
                    raise
                warn(f"  [{label}] 批次 {batch_idx+1} 异常, 重试第 {attempt} 次: {e}")
        raise RuntimeError(f"[{label}] 批次 {batch_idx+1} 重试耗尽")


# ═══════════════════════════════════════════════════════════
# 共享异步批处理
# ═══════════════════════════════════════════════════════════

async def _batch_process(
    prompts: list[str],
    llm_call: LLMCallable,
    max_workers: int,
    label: str,
    source: str,
    error_return_fn=None,
    *,
    warmup_first: bool = False,
) -> list[VerdictDict]:
    """共享异步批处理逻辑。
    :param prompts: 待处理的 prompt 列表
    :param llm_call: LLM 调用函数
    :param max_workers: 最大并发数
    :param label: 日志中的批次标签（如 "LLM"）
    :param source: verdict 的 source 字段值
    :param error_return_fn: 最终失败时的回调，签名为 (i) -> list[VerdictDict]
    :param warmup_first: 是否先串行发送首条请求暖场（预热 KV cache），再并发处理剩余
    """
    if not prompts:
        return []
    max_retries = cfg.get("llm_review_retries", 2)
    sem = asyncio.Semaphore(max_workers)

    async def _process(i: int, prompt: str, total: int) -> list[VerdictDict]:
        try:
            response = await _llm_call_with_retry(
                prompt, llm_call, sem, label, i, total, max_retries,
            )
            parsed = parse_review_response(response)
            warn(f"  [{label}] 批次 {i+1}/{total} ({len(prompt)//4} tokens) → {len(parsed)} verdicts")
            for v in parsed:
                v.setdefault("source", source)
                _normalize_verdict(v)
            return parsed
        except Exception as e:
            warn(f"  [{label}] 批次 {i+1}/{total} ✗ {e}")
            if error_return_fn:
                return error_return_fn(i)
            return []

    results: list[VerdictDict] = []
    if warmup_first and len(prompts) > 1:
        first = prompts[0]
        info(f"  [{label}] 暖场请求 ({len(first)//4} tokens) → 预热 KV cache")
        try:
            result = await _process(0, first, len(prompts))
            results.extend(result)
        except Exception as e:
            warn(f"  [{label}] 暖场请求失败，跳过热身: {e}")
        prompts = prompts[1:]
        start_idx = 1
    else:
        start_idx = 0

    if prompts:
        tasks = [_process(i + start_idx, p, len(prompts) + start_idx) for i, p in enumerate(prompts)]
        for coro in asyncio.as_completed(tasks):
            results.extend(await coro)
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
        batch_size: int = 25,
        max_workers: int | None = None,
        dict_stores: list | None = None,
    ) -> list[VerdictDict]:
        if not self.llm_call:
            raise RuntimeError("LLMBridge 未配置 llm_call 函数")
        if max_workers is None:
            max_workers = cfg.MAX_WORKERS
        merged = merge_multipart_entries(entries)
        prompts = build_review_prompt(
            entries, glossary_entries, auto_verdicts_map,
            fuzzy_results_map, batch_size, merged_context=merged,
            dict_stores=dict_stores,
        )

        def _error_return(i: int) -> list[VerdictDict]:
            return [{
                "key": "__llm_error__", "en_current": "", "zh_current": "",
                "verdict": "🔶 REVIEW", "suggestion": "",
                "reason": f"LLM调用失败 (批次{i+1}): error", "source": SOURCE_LLM_ERROR,
            }]

        return asyncio.run(_batch_process(prompts, self.llm_call, max_workers,
                                          "LLM", SOURCE_LLM_REVIEW, _error_return,
                                          warmup_first=True))

    # ── 未翻译审校 ────────────────────────────────────

    def review_untranslated(
        self,
        entries: list[EntryDict],
        batch_size: int = 1,
        max_workers: int | None = None,
    ) -> list[VerdictDict]:
        """对疑似未翻译条目（en == zh）逐批发 LLM 判断是否确需翻译。"""
        if not self.llm_call:
            raise RuntimeError("LLMBridge 未配置 llm_call 函数")
        if max_workers is None:
            max_workers = cfg.MAX_WORKERS
        prompts = build_untranslated_prompt(entries, batch_size)

        return asyncio.run(_batch_process(prompts, self.llm_call, max_workers,
                                          "未翻译", SOURCE_UNTRANSLATED_REVIEW,
                                          warmup_first=True))

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
        warn(f"[Phase 5] 最终过滤: {len(verdicts)} 条 verdict → {len(prompts)} 批")

        async def _run_all(warmup_first: bool = False) -> tuple[set[str], list[FilterDiscardRecord], dict[str, str], set[str]]:
            sem = asyncio.Semaphore(max_workers)
            discarded_keys: set[str] = set()
            discard_records: list[FilterDiscardRecord] = []
            cleaned_reasons: dict[str, str] = {}
            all_responded: set[str] = set()
            all_input_keys: set[str] = {v.get("key", "") for v in verdicts}
            total_prompts = len(prompts)

            async def _process(i: int, prompt: str) -> tuple[set[str], list[FilterDiscardRecord], dict[str, str], set[str]]:
                try:
                    response = await _llm_call_with_retry(
                        prompt, _call, sem, "Filter", i, total_prompts, 2,
                    )
                    parsed = parse_review_response(response)
                    local_keys: set[str] = set()
                    local_records: list[FilterDiscardRecord] = []
                    local_reasons: dict[str, str] = {}
                    local_responded: set[str] = set()
                    for item in parsed:
                        k = item.get("key", "").strip()
                        if not k:
                            continue
                        local_responded.add(k)
                        vd = item.get("verdict", "").strip()
                        if vd == "PASS":
                            local_keys.add(k)
                            local_records.append({"key": k, "reason": item.get("reason", "").strip()})
                            warn(f"  [Filter] 驳回: {k} — {item.get('reason', '')}")
                        elif vd != "PASS":
                            r = item.get("reason", "").strip()
                            if r:
                                local_reasons[k] = r
                                debug(f"  [Filter] 保留建议: {k} — {r}")
                    warn(f"  [Filter] 批次 {i+1}/{total_prompts} → 驳回 {len(local_keys)} 条, 清洗 {len(local_reasons)} 条")
                    return local_keys, local_records, local_reasons, local_responded
                except Exception as e:
                    warn(f"  [Filter] 批次 {i+1}/{total_prompts} ✗ {e}")
                    return set(), [], {}, set()

            if warmup_first and total_prompts > 1:
                first_prompt = prompts[0]
                info(f"  [Filter] 暖场请求 ({len(first_prompt)//4} tokens) → 预热 KV cache")
                try:
                    keys, records, reasons, responded = await _process(0, first_prompt)
                    discarded_keys.update(keys)
                    discard_records.extend(records)
                    cleaned_reasons.update(reasons)
                    all_responded.update(responded)
                    remaining = prompts[1:]
                except Exception as e:
                    warn(f"  [Filter] 暖场请求失败，继续处理剩余批次: {e}")
                    remaining = prompts
            else:
                remaining = prompts

            if remaining:
                start_idx = total_prompts - len(remaining)
                tasks = [_process(start_idx + i, p) for i, p in enumerate(remaining)]
                for coro in asyncio.as_completed(tasks):
                    keys, records, reasons, responded = await coro
                    discarded_keys.update(keys)
                    discard_records.extend(records)
                    cleaned_reasons.update(reasons)
                    all_responded.update(responded)
            missing = all_input_keys - all_responded
            if missing:
                warn(f"  [Filter] ⚠ LLM 遗漏 {len(missing)} 条, 保留原判: {', '.join(sorted(missing))}")
            return discarded_keys, discard_records, cleaned_reasons, missing

        discarded, discard_records, cleaned_reasons, _ = asyncio.run(_run_all(warmup_first=True))
        warn(f"  最终驳回: {len(discarded)} 条, 清洗 reason: {len(cleaned_reasons)} 条")
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
    verdicts: list[VerdictDict] = []
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
        cat = manual_format_label(key)
        if cat:
            print(f"\n--- [{i+1}/{len(entries)}] [{cat}] {key} ---")
        else:
            print(f"\n--- [{i+1}/{len(entries)}] {key} ---")
        print(f'EN: "{en[:200]}"')
        print(f'ZH: "{zh[:200]}"')
        auto_v = (auto_verdicts_map or {}).get(key)
        if auto_v:
            print(f"  ⚙️ {auto_v.get('verdict', '')}: {auto_v.get('diagnoses_str', '')}")
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
                "reason": reason, "source": SOURCE_INTERACTIVE,
            })
        else:
            print("跳过")
    return verdicts
