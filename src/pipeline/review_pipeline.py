"""
Minecraft 模组翻译审校流水线 — 主编排器。

将原本完全依赖 LLM 的审校流程改造为：
  程序化自动检查 (90%+) → 仅启发式问题交 LLM

统一入口为 run.py。
"""
import json
import sys
from pathlib import Path
from typing import Any

# 复用现有模块
from src.tools.key_alignment import align_keys, load_json, load_json_clean
from src.tools.lang_parser import load_lang, load_lang_text
from src.checkers.format_checker import FormatChecker
from src.checkers.terminology_builder import TerminologyBuilder
from src.tools.fuzzy_search import fuzzy_search_lines
from src.llm.llm_bridge import (
    LLMBridge, filter_for_llm, classify_entries,
    create_openai_llm_call, create_dry_run_llm_call,
    build_review_prompt, interactive_entry_review,
    merge_multipart_entries,
)
from src.reporting.report_generator import ReportGenerator



# ═══════════════════════════════════════════════════════════
# 流水线编排器
# ═══════════════════════════════════════════════════════════

class ReviewPipeline:
    """翻译审校流水线。"""

    def __init__(
        self,
        en_path: str = "",
        zh_path: str = "",
        output_dir: str = "./output",
        *,
        llm_call=None,
        no_llm: bool = False,
        interactive: bool = False,
        dry_run: bool = False,
        min_term_freq: int = 3,
        fuzzy_threshold: float = 60.0,
        fuzzy_top: int = 5,
        batch_size: int = 20,
        pr_alignment: dict | None = None,
    ):
        self.en_path = Path(en_path) if en_path else None
        self.zh_path = Path(zh_path) if zh_path else None
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

        # PR 模式数据
        self.pr_mode = pr_alignment is not None
        self.pr_alignment = pr_alignment
        self.pr_change_meta: dict[str, dict[str, Any]] = {}
        self.pr_warnings: list[dict[str, Any]] = []
        self.zh_only_entries: list[dict[str, Any]] = []
        self.glossary: list[dict[str, Any]] = []
        self.fuzzy_results_map: dict[str, list[dict[str, Any]]] = {}
        self.llm_verdicts: list[dict[str, Any]] = []

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # PR 模式：加载对齐数据
        if self.pr_mode:
            self._load_pr_alignment()

    # ── PR 模式：加载 PR 对齐数据 ──────────────────────────

    def _load_pr_alignment(self) -> None:
        """从 PR 对齐数据构建流水线内部结构。"""
        print("[PR Mode] 加载 PR 对齐数据...")
        data = self.pr_alignment

        # 构建 matched_entries 格式（兼容 Phase 1 输出）
        # 同时附加 _change 字段，供后续 LLM prompt 注入变更上下文
        matched: list[dict[str, str]] = []
        for entry in data.get("all_entries", []):
            key = entry["key"]
            matched.append({
                "key": key,
                "en": entry["en"],
                "zh": entry["zh"],
                "namespace": entry.get("namespace", ""),
                "_change": {
                    "old_en": entry.get("old_en", ""),
                    "old_zh": entry.get("old_zh", ""),
                },
            })

        self.en_data = {e["key"]: e["en"] for e in matched}
        self.zh_data = {e["key"]: e["zh"] for e in matched}

        self.alignment = {
            "matched_entries": matched,
            "missing_zh": [],
            "extra_zh": [],
            "suspicious_untranslated": [],
            "stats": {
                "matched": len(matched),
                "missing_zh": 0,
                "extra_zh": 0,
                "suspicious_untranslated": 0,
                "total_en": len(matched),
                "total_zh": len(matched),
            },
        }

        # 保存 01_alignment.json（PR 模式也生成）
        alignment_path = self.output_dir / "01_alignment.json"
        with open(alignment_path, "w", encoding="utf-8") as f:
            json.dump(self.alignment, f, ensure_ascii=False, indent=2)
        print(f"  已保存: {alignment_path}")

        # 构建 pr_change_meta
        for entry in data.get("all_entries", []):
            key = entry["key"]
            self.pr_change_meta[key] = {
                "en_changed": "old_en" in entry,
                "zh_changed": "old_zh" in entry,
                "old_en": entry.get("old_en", ""),
                "old_zh": entry.get("old_zh", ""),
                "warning": entry.get("review_type") == "en_changed_zh_unchanged",
                "review_type": entry.get("review_type", "normal"),
            }
            if entry.get("review_type") == "zh_only_change":
                self.zh_only_entries.append(entry)

        # 保存 warnings
        self.pr_warnings = data.get("all_warnings", [])
        print(f"  已加载: {len(matched)} 条变更, {len(self.pr_warnings)} 条警告, "
              f"{len(self.zh_only_entries)} 条 ZH-only 变更")

    # ── Phase 1: 键对齐 ───────────────────────────────────

    def run_phase1(self) -> dict[str, Any]:
        """执行键对齐（PR 模式下跳过，直接返回已对齐数据）。"""
        if self.pr_mode:
            print("[Phase 1] PR 模式：跳过键对齐，使用 PR 差异数据...")
            return self.alignment

        print("[Phase 1] 键对齐...")
        warnings: list[str] = []
        if str(self.en_path).endswith(".lang"):
            self.en_data, en_w = load_lang(str(self.en_path))
            self.zh_data, zh_w = load_lang(str(self.zh_path))
            warnings.extend(f"[EN] {w}" for w in en_w)
            warnings.extend(f"[ZH] {w}" for w in zh_w)
        else:
            self.en_data, en_w = load_json_clean(str(self.en_path))
            self.zh_data, zh_w = load_json_clean(str(self.zh_path))
            warnings.extend(f"[EN] {w}" for w in en_w)
            warnings.extend(f"[ZH] {w}" for w in zh_w)
        for w in warnings:
            print(f"  {w}")
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
        """执行全自动格式检查（PR 模式注入额外 warning verdict）。"""
        print("[Phase 3a] 格式检查...")

        checker = FormatChecker()
        matched = self.alignment.get("matched_entries", [])
        all_v: list[dict[str, Any]] = []
        for entry in matched:
            verdicts = checker.check_all(entry)
            all_v.extend(verdicts)

        # PR 模式：注入原文变更但翻译未变更的 warning 作为 SUGGEST verdict
        if self.pr_mode and self.pr_warnings:
            for w in self.pr_warnings:
                key = w["key"]
                meta = self.pr_change_meta.get(key, {})
                old_en = meta.get("old_en", "")
                cur_en = self.en_data.get(key, "")
                all_v.append({
                    "key": key,
                    "verdict": "⚠️ SUGGEST",
                    "source": "pr_warning",
                    "reason": f"原文变更但翻译未变更。旧EN: {old_en[:60]!r} → 新EN: {cur_en[:60]!r}",
                    "suggestion": "",
                })

        self.format_verdicts = all_v
        print(f"  格式问题: {len(all_v)} 条")
        if self.pr_warnings:
            print(f"  PR 警告注入: {len(self.pr_warnings)} 条")

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

        # 筛选需要 LLM 的条目（所有条目一视同仁，含 zh_only_change）
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

        print(f"[Phase 3c] LLM审校: 总{len(matched)}条 → 自动通过{len(auto_pass)}条, "
              f"需审校{len(llm_entries)}条")

        if not llm_entries:
            print("  无需 LLM 审校")
            self.llm_verdicts = []
            return self.llm_verdicts

        # 先做模糊搜索
        self.run_phase3b(llm_entries)

        if self.dry_run:
            merged = merge_multipart_entries(llm_entries)
            prompts = build_review_prompt(
                llm_entries, self.glossary, auto_verdicts_map,
                self.fuzzy_results_map, self.batch_size,
                merged_context=merged,
            )
            total_chars = sum(len(p) for p in prompts)
            print(f"  [DRY RUN] {len(prompts)} 批, ~{total_chars//4} tokens")
            # 显示分类信息
            groups = classify_entries(llm_entries)
            for cat, entries in sorted(groups.items()):
                print(f"    {cat}: {len(entries)} 条")
            self.llm_verdicts = []
            return self.llm_verdicts

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
        rg.generate_markdown_report(str(self.output_dir / "report.md"))

        # 如果有 namespace 信息，按 namespace 拆分报告
        ns_map: dict[str, list[dict[str, Any]]] = {}
        for v in rg.verdicts:
            matched = next((e for e in self.alignment.get("matched_entries", [])
                           if e["key"] == v.get("key")), None)
            if not matched:
                continue
            ns = matched.get("namespace") or v.get("namespace", "")
            if ns:
                ns_map.setdefault(ns, []).append(v)

        if ns_map:
            ns_dir = self.output_dir / "namespaces"
            ns_dir.mkdir(parents=True, exist_ok=True)
            for ns, verdicts in ns_map.items():
                ns_rg = ReportGenerator()
                ns_rg.alignment = self.alignment
                ns_rg.matched_entries = [
                    e for e in self.alignment.get("matched_entries", [])
                    if e.get("namespace") == ns
                ]
                ns_rg.verdicts = verdicts
                ns_rg.compute_stats()
                ns_report = ns_dir / ns / "06_review_report.json"
                ns_report.parent.mkdir(parents=True, exist_ok=True)
                ns_rg.generate_review_report(str(ns_report))
                ns_rg.generate_markdown_report(str(ns_report.parent / "report.md"), ns)
            print(f"  按 namespace 拆分: {len(ns_map)} 组 → {ns_dir}")

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

