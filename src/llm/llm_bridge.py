"""
LLM 交互接口：构建最小化上下文 prompt、调用 LLM、解析响应。
仅对需要启发式判断的条目调用 LLM，大幅降低 token 消耗。

用法:
    from llm_bridge import LLMBridge
    bridge = LLMBridge(api_key="...", model="gpt-4")
    verdicts = bridge.review(entries, context)
"""
import json
import re
from pathlib import Path
from typing import Any, Callable, Protocol

# ═══════════════════════════════════════════════════════════
# 键名分类器（纯规则，不需要 LLM）
# ═══════════════════════════════════════════════════════════

KEY_CATEGORY_RULES: list[tuple[str, str]] = [
    # (前缀模式, 类别名)
    ("advancements.", "进度"),
    ("death.attack.", "死亡信息"),
    ("death.", "死亡信息"),
    ("enchantment.", "魔咒"),
    ("subtitles.", "声音字幕"),
    ("sound.", "声音"),
    ("container.", "容器界面"),
    ("key.", "按键绑定"),
    ("book.", "书籍内容"),
    ("trim_pattern.", "盔甲纹饰"),
    ("trim_material.", "盔甲材料"),
    ("biome.", "生物群系"),
    ("fluid.", "流体"),
    ("fluid_type.", "流体类型"),
    ("effect.", "状态效果"),
    ("entity.", "实体"),
    ("item.", "物品"),
    ("block.", "方块"),
    ("chat.", "聊天消息"),
    ("commands.", "命令"),
    ("selectWorld.", "世界选择"),
    ("menu.", "菜单"),
    ("options.", "选项"),
    ("gui.", "GUI界面"),
    ("jei.", "JEI界面"),
    ("config.", "配置"),
    ("tooltip.", "工具提示"),
    ("category.", "分类"),
    ("attribute.", "属性"),
    ("potion.", "药水"),
]


def classify_key(key: str) -> str:
    """根据键名前缀判断类别。"""
    for prefix, category in KEY_CATEGORY_RULES:
        if key.startswith(prefix):
            return category
    return "其他"


def classify_entries(entries: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """将条目按类别分组。"""
    groups: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        cat = classify_key(entry["key"])
        groups.setdefault(cat, []).append(entry)
    return groups


# ═══════════════════════════════════════════════════════════
# LLM 是否需要审校某条目的判定
# ═══════════════════════════════════════════════════════════

# 必须 LLM 审校的键名类别
LLM_REQUIRED_CATEGORIES: set[str] = {
    "进度", "死亡信息", "魔咒", "声音字幕", "声音",
    "书籍内容", "实体", "状态效果", "药水",
}

# LLM 审校的键名模式（用于描述/风味文本类）
LLM_REQUIRED_PATTERNS: list[str] = [
    ".desc", ".description", ".lore", ".tooltip", ".flavor",
    ".info", ".message", ".text", ".title",
]


def needs_llm_review(entry: dict[str, str]) -> bool:
    """判断某条目是否需要 LLM 审校。"""
    key = entry["key"]
    cat = classify_key(key)
    if cat in LLM_REQUIRED_CATEGORIES:
        return True
    for pattern in LLM_REQUIRED_PATTERNS:
        if pattern in key:
            return True
    # 长文本（>80字符）通常需要 LLM 审校
    if len(entry.get("en", "")) > 80:
        return True
    return False


def filter_for_llm(
    matched_entries: list[dict[str, str]],
    auto_flagged_keys: set[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    从 matched_entries 中筛选需要 LLM 审校的条目。
    返回: (需要LLM审校的条目, 自动通过的条目)
    """
    llm_entries: list[dict[str, str]] = []
    auto_pass: list[dict[str, str]] = []

    for entry in matched_entries:
        key = entry["key"]
        if key in auto_flagged_keys or needs_llm_review(entry):
            llm_entries.append(entry)
        else:
            auto_pass.append(entry)

    return llm_entries, auto_pass


# ═══════════════════════════════════════════════════════════
# Prompt 构建器
# ═══════════════════════════════════════════════════════════

# 风格范本（固定参考，极简版）
STYLE_REFERENCE = """- 物品名: 材质+核心名词, e.g. "铁盾牌"
- 咒语名: 4-6字文学感, e.g. "守护咒文"
- 界面: 直白功能性, e.g. "耐久度: %d"
- 告警: 简短直接, e.g. "无法在此使用"
- 声音字幕: 主体：声音 (全角冒号)
- 键盘键/能量单位: 保留原文 (Shift, Ctrl, FE, RF)"""


def build_entry_block(
    entry: dict[str, str],
    fuzzy_results: list[dict[str, Any]] | None = None,
    auto_verdicts: list[dict[str, Any]] | None = None,
) -> str:
    """为单条 entry 构建 LLM 审校上下文块。"""
    key = entry["key"]
    en = entry.get("en", "")
    zh = entry.get("zh", "")
    cat = classify_key(key)

    lines = [f"[{cat}] `{key}`"]
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

    return "\n".join(lines)


def build_review_prompt(
    entries: list[dict[str, str]],
    glossary_entries: list[dict[str, Any]] | None = None,
    auto_verdicts_map: dict[str, list[dict[str, Any]]] | None = None,
    fuzzy_results_map: dict[str, list[dict[str, Any]]] | None = None,
    batch_size: int = 20,
) -> list[str]:
    """
    构建审校 prompt，分批返回以避免单次过长。

    返回: prompt 字符串列表，每批一个 prompt
    """
    prompts: list[str] = []

    # 分组
    groups = classify_entries(entries)

    for cat, cat_entries in groups.items():
        for i in range(0, len(cat_entries), batch_size):
            batch = cat_entries[i:i + batch_size]
            blocks: list[str] = []

            # 系统指令（每批头部）
            header = f"""你是Minecraft模组简中翻译审校专家。审校以下条目，给出 verdict（PASS/⚠️ SUGGEST/❌ FAIL/🔶 REVIEW）。

## 风格参考
{STYLE_REFERENCE}

## 普适原则
- 以原文为准,逐词理解后评价译文
- 禁止过度发挥,风格差异过大标记🔶 REVIEW或❌ FAIL
- 禁止不适烂梗,直接❌ FAIL
- 专有名词(Patreon/Discord等)保留原文不翻译
- 注意检查语气(黑色幽默/调侃/致敬等)是否被翻译成中性/书面语
"""
            if glossary_entries:
                header += "\n## 术语表\n| 英文术语 | 强制译文 |\n|----------|----------|\n"
                for g in glossary_entries[:30]:
                    if g.get("is_consistent"):
                        header += f"| {g['en_term']} | {g['most_common_translation']} |\n"

            header += f"\n## 待审条目 ({cat}, {len(batch)}条)\n"
            header += "对每条输出: {\"key\": \"...\", \"verdict\": \"...\", \"suggestion\": \"...\", \"reason\": \"...\"}\n"
            header += "PASS条目可不输出。仅输出JSON数组。\n"

            blocks.append(header)

            for j, entry in enumerate(batch):
                key = entry["key"]
                auto_v = auto_verdicts_map.get(key, []) if auto_verdicts_map else []
                fuzzy_r = fuzzy_results_map.get(key, []) if fuzzy_results_map else []
                block = build_entry_block(entry, fuzzy_r, auto_v)
                blocks.append(f"#{j+1} {block}")

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
    ) -> list[dict[str, Any]]:
        """
        分批审校条目，汇总所有 LLM verdict。

        返回: [{key, verdict, suggestion, reason, source: "llm_review"}, ...]
        """
        if not self.llm_call:
            raise RuntimeError("LLMBridge 未配置 llm_call 函数")

        prompts = build_review_prompt(
            entries, glossary_entries, auto_verdicts_map,
            fuzzy_results_map, batch_size,
        )
        all_verdicts: list[dict[str, Any]] = []

        for i, prompt in enumerate(prompts):
            try:
                import sys
                print(f"  [LLM] 批次 {i+1}/{len(prompts)} ({len(prompt)//4} tokens)...", end=" ", flush=True, file=sys.stderr)
                response = self.llm_call(prompt)
                parsed = parse_review_response(response)
                print(f"→ {len(parsed)} verdicts", file=sys.stderr)
                for v in parsed:
                    v["source"] = "llm_review"
                    # 确保必有字段
                    v.setdefault("en_current", "")
                    v.setdefault("zh_current", "")
                    v.setdefault("suggestion", "")
                    v.setdefault("reason", "")
                all_verdicts.extend(parsed)
            except Exception as e:
                all_verdicts.append({
                    "key": "",
                    "en_current": "",
                    "zh_current": "",
                    "verdict": "🔶 REVIEW",
                    "suggestion": "",
                    "reason": f"LLM调用失败: {e}",
                    "source": "llm_error",
                })

        return all_verdicts


# ═══════════════════════════════════════════════════════════
# 示例 LLM 后端 (OpenAI-compatible API)
# ═══════════════════════════════════════════════════════════

def create_openai_llm_call(
    api_key: str,
    model: str = "gpt-4o",
    base_url: str = "https://api.openai.com/v1",
    log_dir: str | None = None,
) -> LLMCallable:
    """创建 OpenAI 兼容的 LLM 调用函数，可选记录 prompt/response 日志。

    :param log_dir: 日志输出目录，为 None 则不记录
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请安装 openai: pip install openai")

    import datetime

    client = OpenAI(api_key=api_key, base_url=base_url)
    call_count = [0]  # mutable counter

    def _log(msg: str) -> None:
        if not log_dir:
            return
        log_path = Path(log_dir) / "08_llm_call_log.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")

    def call(prompt: str) -> str:
        call_count[0] += 1
        n = call_count[0]
        _log(f"=== Call #{n} ({len(prompt)} chars, ~{len(prompt)//4} tokens) ===")
        _log(f"--- Prompt ---\n{prompt}\n--- End Prompt ---")

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一位Minecraft模组简中翻译审校专家。请按要求输出JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        content = resp.choices[0].message.content or ""
        _log(f"--- Response ---\n{content}\n--- End Response ---")
        return content

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
