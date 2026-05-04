"""
LLM 交互接口：构建最小化上下文 prompt、调用 LLM、解析响应。
仅对需要启发式判断的条目调用 LLM，大幅降低 token 消耗。

用法:
    from llm_bridge import LLMBridge
    bridge = LLMBridge(api_key="...", model="gpt-4")
    verdicts = bridge.review(entries, context)
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

from src import config as cfg

# ═══════════════════════════════════════════════════════════
# 键名前缀分组 + 类型专属 Prompt 库（从 review_config.json 加载）
# ═══════════════════════════════════════════════════════════

KEY_PREFIX_PROMPTS: dict[str, tuple[str, str]] = {
    k: tuple(v) for k, v in cfg.KEY_PREFIX_PROMPTS.items()
}

# ═══════════════════════════════════════════════════════════
# 键盘按键 / 鼠标操作检测（用于 LLM prompt 动态补充指南）
# 注意：正则模式在此定义；指南文本从 review_config.json 加载。
#       需要修改指南文案、调整阈值等请去 review_config.json，不要硬编码在此。
# ═══════════════════════════════════════════════════════════

_RE_KEYBOARD_KEY = re.compile(
    r"\b(Shift|Ctrl|Alt|Tab)\b",
    re.IGNORECASE,
)

_RE_MOUSE_OP = re.compile(
    r"(?i)\b(?:left\s*click|right\s*click|left[- ]?mouse|right[- ]?mouse|"
    r"mouse\s*button|scroll\s*wheel|drag|double[-\s]?click|"
    r"middle\s*click|mouse\s*over|hover)\b|"
    r"(?:左键|右键|鼠标|单击|双击|点击|拖拽|滚轮)"
)

_KEYBOARD_GUIDANCE = cfg.KEYBOARD_GUIDANCE
_MOUSE_GUIDANCE = cfg.MOUSE_GUIDANCE


def _detect_input_guidance(entries: list[dict[str, str]]) -> str:
    """扫描一批条目，若检测到键盘按键或鼠标操作则返回补充指南文本。"""
    has_keyboard = False
    has_mouse = False
    for entry in entries:
        en = entry.get("en", "")
        zh = entry.get("zh", "")
        if not has_keyboard and _RE_KEYBOARD_KEY.search(en):
            has_keyboard = True
        if not has_mouse and _RE_MOUSE_OP.search(en + zh):
            has_mouse = True
        if has_keyboard and has_mouse:
            break

    parts: list[str] = []
    if has_keyboard:
        parts.append(_KEYBOARD_GUIDANCE)
    if has_mouse:
        parts.append(_MOUSE_GUIDANCE)
    return "\n".join(parts)


def _group_prefix(key: str) -> str:
    """提取 key 的分组前缀。最长匹配胜出。未匹配返回 '__default__'。"""
    best = ""
    for prefix in KEY_PREFIX_PROMPTS:
        if key.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return best if best else "__default__"


def classify_entries(entries: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """按 key 前缀分组，每组只含一种前缀类型。未匹配的归入 '__default__'。"""
    groups: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        prefix = _group_prefix(entry["key"])
        groups.setdefault(prefix, []).append(entry)
    return groups


def classify_key(key: str) -> str:
    """兼容旧接口：返回类别标签。"""
    prefix = _group_prefix(key)
    if prefix == "__default__":
        return "其他"
    return KEY_PREFIX_PROMPTS.get(prefix, ("其他", ""))[0]


# ═══════════════════════════════════════════════════════════
# LLM 是否需要审校某条目的判定
# ═══════════════════════════════════════════════════════════

LLM_REQUIRED_PREFIXES: set[str] = cfg.LLM_REQUIRED_PREFIXES

LLM_REQUIRED_PATTERNS: list[str] = list(cfg.DESC_KEY_SUFFIXES) + [".title"]

# 术语覆盖率检查：EN 中能匹配到的非术语残渣（忽略标点/空白）
_RE_GLOSSARY_GAP = re.compile(r"[ ,.!?;:'\"()\[\]{}<>\-_/%\t\n\r]+")


def _is_glossary_covered(en: str, zh: str, glossary: list[dict[str, str]]) -> bool:
    """检查 EN 是否被术语表完整覆盖，且 ZH 拼接结果与当前译文一致。

    规则：
    1. 找到 EN 中所有术语表命中的词（最长匹配优先，按位置排序）
    2. 去除这些词后，剩余部分只能是标点/空白
    3. 被覆盖时，按顺序拼接术语的 ZH 值，比对当前译文
    """
    if not glossary:
        return False

    en_lower = en.lower()
    # 收集所有命中：(start, end, zh_val)
    hits: list[tuple[int, int, str]] = []
    # 按 EN 文本长度降序排列术语，确保 "emitter terminal" 优先于 "emitter"
    sorted_glossary = sorted(glossary, key=lambda g: -len(g["en"]))
    for g in sorted_glossary:
        gen = g["en"].lower()
        start = 0
        while True:
            idx = en_lower.find(gen, start)
            if idx == -1:
                break
            hits.append((idx, idx + len(gen), g["zh"]))
            start = idx + 1

    if not hits:
        return False

    # 按位置排序
    hits.sort(key=lambda h: h[0])

    # 检查覆盖：术语之间的间隙只能有空白/标点
    pos = 0
    for start, end, _zh_val in hits:
        if start < pos:
            continue  # 跳过重叠（已覆盖）
        gap = en[pos:start]
        if _RE_GLOSSARY_GAP.sub("", gap):
            return False  # 存在非术语内容
        pos = end

    # 检查尾部
    if _RE_GLOSSARY_GAP.sub("", en[pos:]):
        return False

    # 拼接 ZH 并与实际译文比对（按位置顺序，跳过重叠段）
    expected_parts: list[str] = []
    last_end = 0
    for start, end, zh_val in hits:
        if start >= last_end:
            expected_parts.append(zh_val)
            last_end = end
    return "".join(expected_parts) == zh


def needs_llm_review(entry: dict[str, str]) -> bool:
    """判断某条目是否需要 LLM 审校。"""
    key = entry["key"]
    prefix = _group_prefix(key)
    if prefix in LLM_REQUIRED_PREFIXES:
        return True
    for pattern in LLM_REQUIRED_PATTERNS:
        if pattern in key:
            return True
    if len(entry.get("en", "")) > 80:
        return True
    return False


def filter_for_llm(
    matched_entries: list[dict[str, str]],
    auto_flagged_keys: set[str],
    glossary: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    从 matched_entries 中筛选需要 LLM 审校的条目。

    自动通过条件（全部满足）：
    1. key 未被格式/术语检查命中
    2. 不属于强制 LLM 类别 + EN ≤ 80 字符 + 非描述性 key
    3. 术语表完整覆盖 EN 且 ZH 拼接一致（若有术语表）

    返回: (需要LLM审校的条目, 自动通过的条目)
    """
    llm_entries: list[dict[str, str]] = []
    auto_pass: list[dict[str, str]] = []

    for entry in matched_entries:
        key = entry["key"]
        if key in auto_flagged_keys:
            llm_entries.append(entry)
            continue
        if needs_llm_review(entry):
            llm_entries.append(entry)
            continue
        # 术语覆盖率检查：非术语表覆盖的短条目仍需 LLM 审校
        if glossary and not _is_glossary_covered(
            entry.get("en", ""), entry.get("zh", ""), glossary,
        ):
            llm_entries.append(entry)
            continue
        auto_pass.append(entry)

    return llm_entries, auto_pass


# ═══════════════════════════════════════════════════════════
# Prompt 构建器
# ═══════════════════════════════════════════════════════════

# 风格范本（从配置加载）
STYLE_REFERENCE = cfg.STYLE_REFERENCE


def build_entry_block(
    entry: dict[str, str],
    index: int = 0,
    fuzzy_results: list[dict[str, Any]] | None = None,
    auto_verdicts: list[dict[str, Any]] | None = None,
    glossary_entries: list[dict[str, str]] | None = None,
) -> str:
    """为单条 entry 构建 LLM 审校上下文块。key 值在最前面，LLM 应直接引用。"""
    key = entry["key"]
    en = entry.get("en", "")
    zh = entry.get("zh", "")

    lines = [f"key: `{key}`"]
    lines.append(f'EN: "{en[:300]}"')
    lines.append(f'ZH: "{zh[:300]}"')

    if auto_verdicts:
        for v in auto_verdicts:
            lines.append(f"  自动检查: {v['verdict']} — {v['reason']}")

    if fuzzy_results:
        lines.append("  模糊匹配:")
        for fr in fuzzy_results[:3]:
            lines.append(
                f"    sim={fr['similarity']}% | EN: \"{fr['en'][:100]}\" | ZH: \"{fr['zh'][:100]}\""
            )

    # 术语提示：只附上与当前 EN 原文相关的术语
    if glossary_entries:
        en_lower = en.lower()
        hints: list[str] = []
        for g in glossary_entries:
            if g["en"].lower() in en_lower:
                hints.append(f"\"{g['en']}\" → \"{g['zh']}\"")
        if hints:
            lines.append(f"  术语: {', '.join(hints[:5])}")

    return "\n".join(lines)


def build_review_prompt(
    entries: list[dict[str, str]],
    glossary_entries: list[dict[str, str]] | None = None,
    auto_verdicts_map: dict[str, list[dict[str, Any]]] | None = None,
    fuzzy_results_map: dict[str, list[dict[str, Any]]] | None = None,
    batch_size: int = 20,
) -> list[str]:
    """
    构建审校 prompt，按 key 前缀分组，每组用专属审查重点。
    每批最多 batch_size 条。未匹配前缀用默认 prompt。
    """
    prompts: list[str] = []

    groups = classify_entries(entries)

    for prefix, group_entries in groups.items():
        cat_label, focus_notes = KEY_PREFIX_PROMPTS.get(
            prefix, ("其他", cfg.DEFAULT_REVIEW_FOCUS)
        )
        for i in range(0, len(group_entries), batch_size):
            batch = group_entries[i:i + batch_size]

            header = f"""{cfg.REVIEW_HEADER_PREFIX}。当前类型: {cat_label}（{prefix}*）。

## 审查重点
{focus_notes}

## 风格参考
{STYLE_REFERENCE}

## 普适原则
{cfg.REVIEW_PRINCIPLES}
"""

            header += f"\n## 待审条目 ({len(batch)}条)\n"
            header += cfg.REVIEW_INSTRUCTION + "\n"

            # 动态补充：检测到键盘/鼠标相关内容时追加专项指南
            input_guidance = _detect_input_guidance(batch)
            if input_guidance:
                header += f"\n## 输入设备翻译专项指南\n{input_guidance}\n"

            blocks = [header]
            for j, entry in enumerate(batch):
                key = entry["key"]
                auto_v = auto_verdicts_map.get(key, []) if auto_verdicts_map else []
                fuzzy_r = fuzzy_results_map.get(key, []) if fuzzy_results_map else []
                block = build_entry_block(entry, j + 1, fuzzy_r, auto_v, glossary_entries)
                blocks.append(block)

            prompts.append("\n\n".join(blocks))

    return prompts


# ═══════════════════════════════════════════════════════════
# 响应解析器
# ═══════════════════════════════════════════════════════════

def parse_review_response(response: str) -> list[dict[str, Any]]:
    """从 LLM 响应中解析 verdict JSON 数组。"""
    # 尝试直接解析整个响应
    try:
        data = json.loads(response)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "verdicts" in data:
            return data["verdicts"]
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 数组
    json_match = re.search(r"\[.*\]", response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # 尝试逐行解析 JSON 对象
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
# Phase 5: 最终 LLM 过滤 —— 审视已汇总的 verdict 并筛除误报
# ═══════════════════════════════════════════════════════════

def build_filter_prompt(
    verdicts: list[dict[str, Any]],
    batch_size: int = 50,
) -> list[str]:
    """为最终过滤构建 prompt，展示 EN/ZH/verdict/reason/suggestion。"""
    prompts: list[str] = []

    for i in range(0, len(verdicts), batch_size):
        batch = verdicts[i:i + batch_size]

        header = f"""{cfg.REVIEW_HEADER_PREFIX}。

## 任务
以下是自动检查和LLM审校后汇总的翻译问题列表。请逐条判断是否需要驳回（不提出）。

## 问题列表 ({len(batch)}条)
"""
        lines: list[str] = []
        for j, v in enumerate(batch):
            key = v.get("key", "")
            en = v.get("en_current", "")
            zh = v.get("zh_current", "")
            verdict = v.get("verdict", "")
            reason = v.get("reason", "")
            suggestion = v.get("suggestion", "")

            block = f"### 条目 {j+1}\n"
            block += f"key: `{key}`\n"
            block += f'EN: "{en[:200]}"\n'
            block += f'ZH: "{zh[:200]}"\n'
            block += f"判定: {verdict}\n"
            block += f"问题: {reason}\n"
            if suggestion:
                block += f"建议: {suggestion}\n"
            lines.append(block)

        prompt = header + cfg.FILTER_INSTRUCTION + "\n\n" + "\n".join(lines)
        prompts.append(prompt)

    return prompts


# ═══════════════════════════════════════════════════════════
# LLM 调用接口
# ═══════════════════════════════════════════════════════════

# LLM 调用函数的类型签名
LLMCallable = Callable[[str], str]


class LLMBridge:
    """
    LLM 交互桥接。不绑定特定 LLM SDK，用户提供 callable。
    """

    def __init__(self, llm_call: LLMCallable | None = None):
        """
        :param llm_call: 接受 prompt 字符串，返回响应字符串的函数
        """
        self.llm_call = llm_call

    def review_batch(
        self,
        entries: list[dict[str, str]],
        glossary_entries: list[dict[str, Any]] | None = None,
        auto_verdicts_map: dict[str, list[dict[str, Any]]] | None = None,
        fuzzy_results_map: dict[str, list[dict[str, Any]]] | None = None,
        batch_size: int = 20,
        max_workers: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        异步分批审校条目，汇总所有 LLM verdict。
        """
        if not self.llm_call:
            raise RuntimeError("LLMBridge 未配置 llm_call 函数")

        if max_workers is None:
            from src.config import MAX_WORKERS as _mw
            max_workers = _mw

        prompts = build_review_prompt(
            entries, glossary_entries, auto_verdicts_map,
            fuzzy_results_map, batch_size,
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

    def filter_verdicts(
        self,
        verdicts: list[dict[str, Any]],
        batch_size: int | None = None,
        max_workers: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """
        最终过滤：将已汇总的 verdict 交给 LLM 审视，筛除误报。
        返回 (保留的 verdict 列表, 驳回记录列表 [{key, reason}]).
        """
        if not self.llm_call:
            return verdicts, []

        if batch_size is None:
            batch_size = cfg.FILTER_BATCH_SIZE
        if max_workers is None:
            max_workers = cfg.MAX_WORKERS

        prompts = build_filter_prompt(verdicts, batch_size)
        print(f"[Phase 5] 最终过滤: {len(verdicts)} 条 verdict → {len(prompts)} 批", file=sys.stderr)

        async def _run_all() -> tuple[set[str], list[dict[str, str]]]:
            sem = asyncio.Semaphore(max_workers)
            discarded_keys: set[str] = set()
            discard_records: list[dict[str, str]] = []

            async def _process(i: int, prompt: str) -> tuple[set[str], list[dict[str, str]]]:
                async with sem:
                    try:
                        loop = asyncio.get_running_loop()
                        response = await loop.run_in_executor(None, self.llm_call, prompt)
                        parsed = parse_review_response(response)
                        local_keys: set[str] = set()
                        local_records: list[dict[str, str]] = []
                        for item in parsed:
                            if item.get("action") == "discard":
                                k = item.get("key", "")
                                r = item.get("reason", "")
                                if k:
                                    local_keys.add(k)
                                    local_records.append({"key": k, "reason": r})
                                    print(f"  [Filter] 驳回: {k} — {r}", file=sys.stderr)
                        print(f"  [Filter] 批次 {i+1}/{len(prompts)} → 驳回 {len(local_keys)} 条",
                              file=sys.stderr)
                        return local_keys, local_records
                    except Exception as e:
                        print(f"  [Filter] 批次 {i+1}/{len(prompts)} ✗ {e}", file=sys.stderr)
                        return set(), []

            tasks = [_process(i, p) for i, p in enumerate(prompts)]
            for coro in asyncio.as_completed(tasks):
                keys, records = await coro
                discarded_keys.update(keys)
                discard_records.extend(records)
            return discarded_keys, discard_records

        discarded, discard_records = asyncio.run(_run_all())
        print(f"  最终驳回: {len(discarded)} 条", file=sys.stderr)

        filtered = [v for v in verdicts if v.get("key") not in discarded]
        return filtered, discard_records


# ═══════════════════════════════════════════════════════════
# 示例 LLM 后端 (OpenAI-compatible API)
# ═══════════════════════════════════════════════════════════

def create_openai_llm_call(
    api_key: str,
    model: str = "gpt-4o",
    base_url: str = "https://api.openai.com/v1",
    log_dir: str = "logs",
) -> LLMCallable:
    """创建 OpenAI 兼容的 LLM 调用函数，记录 prompt/response 日志（自动滚动）。

    :param log_dir: 日志目录，默认 logs/
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请安装 openai: pip install openai")

    import datetime
    import time

    client = OpenAI(api_key=api_key, base_url=base_url)
    call_count = [0]  # mutable counter

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)
    latest_path = log_dir_path / "latest.log"

    # 滚动旧日志
    if latest_path.exists():
        mtime = latest_path.stat().st_mtime
        archive_name = time.strftime("%Y%m%d-%H%M%S", time.localtime(mtime))
        archive_path = log_dir_path / f"latest.{archive_name}.log"
        latest_path.rename(archive_path)

    def _log(level: str, msg: str) -> None:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {msg}\n"
        with open(latest_path, "a", encoding="utf-8") as f:
            f.write(line)

    def call(prompt: str) -> str:
        call_count[0] += 1
        n = call_count[0]
        _log("INFO", f"=== Call #{n} ({len(prompt)} chars, ~{len(prompt)//4} tokens) ===")
        _log("INFO", f"Prompt:\n{prompt}")

        retries = 0
        while True:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": cfg.REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )
                content = resp.choices[0].message.content or ""
                _log("INFO", f"Response:\n{content}")
                return content
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate" in err_str:
                    delay = min(2 ** retries, 60)
                    retries += 1
                    print(f"  [429] 速率限制, {delay}s 后重试 (第{retries}次)...", file=sys.stderr)
                    time.sleep(delay)
                else:
                    raise

    return call


def create_dry_run_llm_call() -> LLMCallable:
    """创建干运行 LLM 调用（不实际调用，返回空结果，用于测试）。"""
    def call(prompt: str) -> str:
        print(f"[DRY RUN] Prompt length: {len(prompt)} chars")
        return "[]"
    return call


# ═══════════════════════════════════════════════════════════
# 交互模式：逐条向用户提问
# ═══════════════════════════════════════════════════════════

def interactive_entry_review(
    entries: list[dict[str, str]],
    auto_verdicts_map: dict[str, list[dict[str, Any]]] | None = None,
    fuzzy_results_map: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """
    交互式审校：在终端逐条展示条目，让用户手动判定。
    用于无 LLM API 时的替代方案。
    """
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
                "key": key,
                "en_current": en,
                "zh_current": zh,
                "verdict": verdict,
                "suggestion": suggestion,
                "reason": reason,
                "source": "interactive",
            })
        else:
            print("跳过")

    return verdicts


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="构建 LLM 审校 prompt 并（可选）调用 LLM"
    )
    parser.add_argument("--alignment", required=True,
                        help="alignment.json 路径")
    parser.add_argument("--glossary", default=None,
                        help="glossary.json 路径（术语表）")
    parser.add_argument("--auto-verdicts", default=None,
                        help="format/terminology verdicts JSON 路径")
    parser.add_argument("--output-prompt", default=None,
                        help="将 prompt 保存到文件（不调用 LLM）")
    parser.add_argument("--output-verdicts", default=None,
                        help="将 LLM verdicts 保存到文件")
    parser.add_argument("--api-key", default=None,
                        help="OpenAI API key（可选，也可设环境变量 OPENAI_API_KEY）")
    parser.add_argument("--model", default="gpt-4o",
                        help="LLM 模型名，默认 gpt-4o")
    parser.add_argument("--base-url", default="https://api.openai.com/v1",
                        help="API base URL")
    parser.add_argument("--interactive", action="store_true",
                        help="交互模式：逐条手动审校")
    parser.add_argument("--dry-run", action="store_true",
                        help="干运行：只生成 prompt 不调用 LLM")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="每批条目数，默认20")

    args = parser.parse_args()
    import os

    try:
        with open(args.alignment, "r", encoding="utf-8") as f:
            alignment = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    matched = alignment.get("matched_entries", [])

    # 加载术语表
    glossary = None
    if args.glossary:
        with open(args.glossary, "r", encoding="utf-8") as f:
            glossary = json.load(f)

    # 加载已有自动 verdicts
    auto_verdicts_map: dict[str, list[dict[str, Any]]] = {}
    if args.auto_verdicts:
        with open(args.auto_verdicts, "r", encoding="utf-8") as f:
            av_data = json.load(f)
            for v in av_data.get("verdicts", av_data if isinstance(av_data, list) else []):
                k = v.get("key", "")
                auto_verdicts_map.setdefault(k, []).append(v)

    # 筛选需要 LLM 的条目
    auto_flagged_keys = set(auto_verdicts_map.keys())
    llm_entries, auto_pass = filter_for_llm(matched, auto_flagged_keys)

    print(f"总条目: {len(matched)} | 自动通过: {len(auto_pass)} | 需LLM审校: {len(llm_entries)}")

    if args.interactive:
        verdicts = interactive_entry_review(llm_entries, auto_verdicts_map)
        if args.output_verdicts:
            with open(args.output_verdicts, "w", encoding="utf-8") as f:
                json.dump(verdicts, f, ensure_ascii=False, indent=2)
        print(f"\n交互审校完成: {len(verdicts)} 条判定")
        return

    # 构建 prompt
    prompts = build_review_prompt(
        llm_entries, glossary, auto_verdicts_map,
        None, args.batch_size,
    )

    if args.output_prompt:
        with open(args.output_prompt, "w", encoding="utf-8") as f:
            for i, p in enumerate(prompts):
                f.write(f"=== Batch {i+1} ===\n")
                f.write(p)
                f.write("\n\n")
        print(f"Prompt 已保存到 {args.output_prompt}")

    if args.dry_run:
        total_chars = sum(len(p) for p in prompts)
        print(f"干运行: {len(prompts)} 批, 总 {total_chars} 字符, 约 {total_chars//4} tokens")
        return

    # 调用 LLM
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("错误: 需要 --api-key 或设置 OPENAI_API_KEY 环境变量")
        sys.exit(1)

    llm_call = create_openai_llm_call(api_key, args.model, args.base_url)
    bridge = LLMBridge(llm_call)
    verdicts = bridge.review_batch(
        llm_entries, glossary, auto_verdicts_map,
        None, args.batch_size,
    )

    if args.output_verdicts:
        with open(args.output_verdicts, "w", encoding="utf-8") as f:
            json.dump(verdicts, f, ensure_ascii=False, indent=2)

    print(f"LLM审校完成: {len(verdicts)} 条判定")


if __name__ == "__main__":
    main()
