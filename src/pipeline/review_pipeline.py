"""
Minecraft 模组翻译审校流水线 — 主编排器。

将原本完全依赖 LLM 的审校流程改造为：
  程序化自动检查 (90%+) → 仅启发式问题交 LLM

用法:
    # 完整流水线（含 LLM）
    python review_pipeline.py --en en_us.json --zh zh_cn.json --output-dir ./output/ --api-key sk-xxx

    # 仅自动检查（不调 LLM）
    python review_pipeline.py --en en_us.json --zh zh_cn.json --output-dir ./output/ --no-llm

    # 交互模式（手动逐条审校）
    python review_pipeline.py --en en_us.json --zh zh_cn.json --output-dir ./output/ --interactive

    # 干运行（查看会将多少条目发给 LLM）
    python review_pipeline.py --en en_us.json --zh zh_cn.json --output-dir ./output/ --dry-run
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# 复用现有模块
from src.tools.key_alignment import align_keys, load_json
from src.checkers.format_checker import FormatChecker
from src.checkers.terminology_builder import TerminologyBuilder
from src.tools.fuzzy_search import fuzzy_search_lines
from src.llm.llm_bridge import (
    LLMBridge, filter_for_llm, classify_entries,
    create_openai_llm_call, create_dry_run_llm_call,
    build_review_prompt, interactive_entry_review,
)
from src.reporting.report_generator import ReportGenerator


# ═══════════════════════════════════════════════════════════
# 流水线编排器
# ═══════════════════════════════════════════════════════════

class ReviewPipeline:
    """翻译审校流水线。"""

    def __init__(
        self,
        en_path: str,
        zh_path: str,
        output_dir: str,
        *,
        llm_call=None,
        no_llm: bool = False,
        interactive: bool = False,
        dry_run: bool = False,
        min_term_freq: int = 3,
        fuzzy_threshold: float = 60.0,
        fuzzy_top: int = 5,
        batch_size: int = 20,
    ):
        self.en_path = Path(en_path)
        self.zh_path = Path(zh_path)
        self.output_dir = Path(output_dir)
        self.llm_call = llm_call
        self.no_llm = no_llm
        self.interactive = interactive
        self.dry_run = dry_run
        self.min_term_freq = min_term_freq
        self.fuzzy_threshold = fuzzy_threshold
        self.fuzzy_top = fuzzy_top
        self.batch_size = batch_size

        # 中间数据
        self.en_data: dict[str, str] = {}
        self.zh_data: dict[str, str] = {}
        self.alignment: dict[str, Any] = {}
        self.format_verdicts: list[dict[str, Any]] = []
        self.term_verdicts: list[dict[str, Any]] = []
        self.glossary: list[dict[str, Any]] = []
        self.fuzzy_results_map: dict[str, list[dict[str, Any]]] = {}
        self.llm_verdicts: list[dict[str, Any]] = []

        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: 键对齐 ───────────────────────────────────

    def run_phase1(self) -> dict[str, Any]:
        """执行键对齐。"""
        print("[Phase 1] 键对齐...")
        self.en_data = load_json(str(self.en_path))
        self.zh_data = load_json(str(self.zh_path))
        self.alignment = align_keys(self.en_data, self.zh_data)

        stats = self.alignment["stats"]
        print(f"  ✅ 已对齐: {stats['matched']} | ❌ 未翻译: {stats['missing_zh']} | ⚠️ 多余键: {stats['extra_zh']} | 🔶 疑似未翻译: {stats['suspicious_untranslated']}")

        # 保存 01_alignment.json
        alignment_path = self.output_dir / "01_alignment.json"
        with open(alignment_path, "w", encoding="utf-8") as f:
            json.dump(self.alignment, f, ensure_ascii=False, indent=2)
        print(f"  已保存: {alignment_path}")

        return self.alignment

    # ── Phase 2: 术语提取 ─────────────────────────────────

    def run_phase2(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """执行术语提取、归并、构建术语表、一致性检查。"""
        print("[Phase 2] 术语提取与一致性检查...")

        cache_path = "lemma_cache.json"  # 项目根目录，可提交共享
        tb = TerminologyBuilder(cache_path=cache_path)
        tb.load(self.en_data, self.zh_data, self.alignment)
        tb.extract(min_freq=2, max_ngram=3)
        # 缓存查表 → 模糊聚类 → 纯程序提取术语表
        tb.merge_lemmas(llm_call=self.llm_call)
        self.glossary = tb.build_glossary()
        self.term_verdicts = tb.check_consistency()

        print(f"  术语表: {len(self.glossary)} 条")
        print(f"  术语不一致 verdicts: {len(self.term_verdicts)} 条")

        # 保存术语表
        glossary_path = self.output_dir / "02_terminology_glossary.json"
        with open(glossary_path, "w", encoding="utf-8") as f:
            json.dump(self.glossary, f, ensure_ascii=False, indent=2)
        print(f"  已保存: {glossary_path}")

        return self.glossary, self.term_verdicts

    # ── Phase 3a: 格式检查 ────────────────────────────────

    def run_phase3a(self) -> list[dict[str, Any]]:
        """执行全自动格式检查。"""
        print("[Phase 3a] 格式检查...")

        checker = FormatChecker()
        matched = self.alignment.get("matched_entries", [])
        all_v: list[dict[str, Any]] = []
        for entry in matched:
            verdicts = checker.check_all(entry)
            all_v.extend(verdicts)

        self.format_verdicts = all_v
        print(f"  格式问题: {len(all_v)} 条")

        # 保存
        fmt_path = self.output_dir / "03_format_verdicts.json"
        with open(fmt_path, "w", encoding="utf-8") as f:
            json.dump({
                "total_checked": len(matched),
                "issues_found": len(all_v),
                "verdicts": all_v,
            }, f, ensure_ascii=False, indent=2)

        return all_v

    # ── Phase 3b: 模糊搜索 ────────────────────────────────

    def run_phase3b(
        self,
        llm_entries: list[dict[str, str]],
    ) -> dict[str, list[dict[str, Any]]]:
        """对需要 LLM 审校的关键条目执行模糊搜索。"""
        print("[Phase 3b] 模糊搜索...")

        # 仅对需要 LLM 的条目中匹配关键模式的做模糊搜索
        fuzzy_trigger_patterns = [".desc", "death.attack.", "advancements."]
        to_search: list[dict[str, str]] = []
        for entry in llm_entries:
            key = entry["key"]
            if any(p in key for p in fuzzy_trigger_patterns):
                to_search.append(entry)

        self.fuzzy_results_map = {}
        for entry in to_search:
            key = entry["key"]
            en = entry.get("en", "")
            if not en or not isinstance(en, str):
                continue
            results = fuzzy_search_lines(
                query=en,
                en_entries=self.en_data,
                zh_entries=self.zh_data,
                top_n=self.fuzzy_top,
                threshold=self.fuzzy_threshold,
            )
            # 过滤掉自身
            results = [r for r in results if r.get("key") != key]
            if results:
                self.fuzzy_results_map[key] = results

        print(f"  模糊搜索: {len(to_search)} 条查询, {len(self.fuzzy_results_map)} 条有结果")

        # 保存
        if self.fuzzy_results_map:
            fuzzy_path = self.output_dir / "04_fuzzy_results.json"
            with open(fuzzy_path, "w", encoding="utf-8") as f:
                json.dump(self.fuzzy_results_map, f, ensure_ascii=False, indent=2)

        return self.fuzzy_results_map

    # ── Phase 3c: LLM 审校 / 交互审校 ─────────────────────

    def run_phase3c(self) -> list[dict[str, Any]]:
        """筛选需要 LLM 的条目并执行审校。"""
        matched = self.alignment.get("matched_entries", [])

        # 收集自动检查标记的 key
        auto_flagged_keys: set[str] = set()
        for v in self.format_verdicts:
            auto_flagged_keys.add(v.get("key", ""))
        for v in self.term_verdicts:
            auto_flagged_keys.add(v.get("key", ""))

        # 收集"疑似未翻译"的 key（zh==en 且非代码/专有名词），这些不交 LLM
        untranslated_keys: set[str] = set()
        for v in self.format_verdicts:
            if "值相同" in v.get("reason", ""):
                untranslated_keys.add(v.get("key", ""))

        # 筛选需要 LLM 的条目
        llm_entries, auto_pass = filter_for_llm(matched, auto_flagged_keys, self.glossary)

        # 剔除疑似未翻译条目（格式检查已给出 ❌ FAIL，无需 LLM 重复判断）
        if untranslated_keys:
            removed = len(llm_entries)
            llm_entries = [e for e in llm_entries if e["key"] not in untranslated_keys]
            removed -= len(llm_entries)
            if removed:
                print(f"  跳过疑似未翻译: {removed} 条")

        # 构建自动 verdict 映射（供 LLM 参考）
        auto_verdicts_map: dict[str, list[dict[str, Any]]] = {}
        for v in self.format_verdicts + self.term_verdicts:
            k = v.get("key", "")
            if k:
                auto_verdicts_map.setdefault(k, []).append(v)

        print(f"[Phase 3c] LLM审校: 总{len(matched)}条 → 自动通过{len(auto_pass)}条, 需审校{len(llm_entries)}条")

        if not llm_entries:
            print("  无需 LLM 审校")
            return []

        # 先做模糊搜索
        self.run_phase3b(llm_entries)

        if self.dry_run:
            prompts = build_review_prompt(
                llm_entries, self.glossary, auto_verdicts_map,
                self.fuzzy_results_map, self.batch_size,
            )
            total_chars = sum(len(p) for p in prompts)
            print(f"  [DRY RUN] {len(prompts)} 批, ~{total_chars//4} tokens")
            # 显示分类信息
            groups = classify_entries(llm_entries)
            for cat, entries in sorted(groups.items()):
                print(f"    {cat}: {len(entries)} 条")
            return []

        if self.interactive:
            print("  进入交互审校模式...")
            self.llm_verdicts = interactive_entry_review(
                llm_entries, auto_verdicts_map, self.fuzzy_results_map,
            )
        elif self.llm_call and not self.no_llm:
            bridge = LLMBridge(self.llm_call)
            self.llm_verdicts = bridge.review_batch(
                llm_entries, self.glossary, auto_verdicts_map,
                self.fuzzy_results_map, self.batch_size,
            )
        else:
            print("  跳过 LLM 审校 (--no-llm)")
            # 自动 verdict 作为最终 verdict
            self.llm_verdicts = [
                v for v in self.format_verdicts + self.term_verdicts
                if v.get("verdict") != "PASS"
            ]

        print(f"  LLM verducts: {len(self.llm_verdicts)} 条")

        # 保存 LLM verdicts
        if self.llm_verdicts:
            llm_path = self.output_dir / "05_llm_verdicts.json"
            with open(llm_path, "w", encoding="utf-8") as f:
                json.dump(self.llm_verdicts, f, ensure_ascii=False, indent=2)

        return self.llm_verdicts

    # ── Phase 4: 报告生成 ─────────────────────────────────

    def run_phase4(self) -> None:
        """生成审校报告。"""
        print("[Phase 4] 报告生成...")

        rg = ReportGenerator()
        rg.load_alignment(self.alignment)
        rg.collect(
            self.format_verdicts,
            self.term_verdicts,
            self.llm_verdicts,
        )

        review_path = self.output_dir / "06_review_report.json"

        rg.generate_review_report(str(review_path))

        print(f"  审校报告: {review_path}")
        rg.print_summary()
        rg.print_verdict_table()

    # ── Phase 5: 最终 LLM 过滤 ────────────────────────────

    def run_phase5(self) -> None:
        """最终 LLM 审视：筛除汇总报告中的误报，重新生成报告。"""
        if not self.llm_call or self.no_llm or self.dry_run:
            return

        print("[Phase 5] 最终 LLM 过滤...")

        # 读取 Phase 4 生成的报告
        review_path = self.output_dir / "06_review_report.json"
        with open(review_path, "r", encoding="utf-8") as f:
            report = json.load(f)

        verdicts = report.get("verdicts", [])
        if not verdicts:
            print("  无 verdict 需要过滤")
            return

        bridge = LLMBridge(self.llm_call)
        filtered, discard_records = bridge.filter_verdicts(verdicts)
        removed = len(discard_records)
        print(f"  驳回 {removed} 条, 保留 {len(filtered)} 条")

        # 保存驳回记录
        discard_path = self.output_dir / "07_filter_discards.json"
        with open(discard_path, "w", encoding="utf-8") as f:
            json.dump(discard_records, f, ensure_ascii=False, indent=2)
        print(f"  驳回记录: {discard_path}")

        if removed == 0:
            return

        # 重新统计数据
        stats = {
            "total": self.alignment["stats"]["matched"],
            "PASS": self.alignment["stats"]["matched"] - len(filtered),
            "⚠️ SUGGEST": sum(1 for v in filtered if v.get("verdict") == "⚠️ SUGGEST"),
            "❌ FAIL": sum(1 for v in filtered if v.get("verdict") == "❌ FAIL"),
            "🔶 REVIEW": sum(1 for v in filtered if v.get("verdict") == "🔶 REVIEW"),
        }

        # 覆盖报告
        report["stats"] = stats
        report["verdicts"] = filtered
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  已更新: {review_path}")

    # ── 完整流水线 ────────────────────────────────────────

    def run(self) -> None:
        """运行完整审校流水线。"""
        print(f"{'='*60}")
        print(f"Minecraft 模组翻译审校流水线")
        print(f"  EN: {self.en_path}")
        print(f"  ZH: {self.zh_path}")
        print(f"  输出: {self.output_dir}")
        if self.dry_run:
            print(f"  模式: 干运行")
        elif self.interactive:
            print(f"  模式: 交互审校")
        elif self.no_llm:
            print(f"  模式: 仅自动检查")
        print(f"{'='*60}")

        try:
            self.run_phase1()
            self.run_phase2()
            self.run_phase3a()
            self.run_phase3c()
            self.run_phase4()
            self.run_phase5()
        except Exception as e:
            print(f"\n错误: {e}", file=sys.stderr)
            raise


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minecraft 模组翻译审校流水线 — 自动检查 + LLM 启发式审校",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 完整流水线
  python review_pipeline.py --en en_us.json --zh zh_cn.json -o ./output/ --api-key sk-xxx

  # 仅自动检查
  python review_pipeline.py --en en_us.json --zh zh_cn.json -o ./output/ --no-llm

  # 交互模式
  python review_pipeline.py --en en_us.json --zh zh_cn.json -o ./output/ --interactive

  # 查看会将多少条目发给 LLM
  python review_pipeline.py --en en_us.json --zh zh_cn.json -o ./output/ --dry-run
        """,
    )

    parser.add_argument("--en", required=True, help="en_us.json 路径")
    parser.add_argument("--zh", required=True, help="zh_cn.json 路径")
    parser.add_argument("-o", "--output-dir", required=True, help="输出目录")
    parser.add_argument("--api-key", default=None,
                        help="OpenAI API key（或设环境变量 OPENAI_API_KEY）")
    parser.add_argument("--model", default="gpt-4o", help="LLM 模型")
    parser.add_argument("--base-url", default="https://api.openai.com/v1",
                        help="API base URL")
    parser.add_argument("--no-llm", action="store_true",
                        help="跳过 LLM 审校，仅自动检查")
    parser.add_argument("--interactive", action="store_true",
                        help="交互模式：逐条手动判定")
    parser.add_argument("--dry-run", action="store_true",
                        help="干运行：显示统计不调 LLM")
    parser.add_argument("--min-term-freq", type=int, default=3,
                        help="术语最低频次阈值，默认3")
    parser.add_argument("--fuzzy-threshold", type=float, default=60.0,
                        help="模糊搜索相似度阈值，默认60")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="LLM 每批条目数，默认20")

    args = parser.parse_args()

    # 验证输入文件
    if not os.path.exists(args.en):
        print(f"错误: EN 文件不存在: {args.en}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.zh):
        print(f"错误: ZH 文件不存在: {args.zh}", file=sys.stderr)
        sys.exit(1)

    # 构建 LLM 调用函数
    llm_call = None
    if not args.no_llm and not args.interactive and not args.dry_run:
        api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("警告: 未提供 API key，将跳过 LLM 审校（使用 --api-key 或 --no-llm）")
        else:
            llm_call = create_openai_llm_call(api_key, args.model, args.base_url)

    pipeline = ReviewPipeline(
        en_path=args.en,
        zh_path=args.zh,
        output_dir=args.output_dir,
        llm_call=llm_call,
        no_llm=args.no_llm,
        interactive=args.interactive,
        dry_run=args.dry_run,
        min_term_freq=args.min_term_freq,
        fuzzy_threshold=args.fuzzy_threshold,
        batch_size=args.batch_size,
    )
    pipeline.run()


if __name__ == "__main__":
    main()
