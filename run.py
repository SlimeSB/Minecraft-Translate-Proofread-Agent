"""Minecraft 模组翻译审校工具 — CLI 入口。

用法:
    python run.py --en en_us.json --zh zh_cn.json -o ./output/
    python run.py --en en_us.json --zh zh_cn.json -o ./output/ --dry-run
    python run.py --en en_us.json --zh zh_cn.json -o ./output/ --no-llm
    python run.py --en en_us.json --zh zh_cn.json -o ./output/ --interactive

LLM 配置（通过环境变量）:
    REVIEW_OPENAI_API_KEY    必需，OpenAI 兼容 API key（DeepSeek 等）
    REVIEW_OPENAI_BASE_URL   可选，默认 https://api.deepseek.com
    REVIEW_OPENAI_MODEL      可选，默认 deepseek-v4-flash
"""
import argparse
import os
import sys

# 强制 UTF-8 输出（兼容 Windows GBK 终端）。
# 仅在 stdout 是终端时 reconfigure（管道场景会破坏 PowerShell 的 OutputEncoding）。
if sys.stdout.encoding != "utf-8" and sys.stdout.isatty():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.pipeline.review_pipeline import ReviewPipeline
from src.llm.llm_bridge import create_openai_llm_call
from src import config as cfg


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minecraft 模组翻译审校流水线 — 自动检查 + LLM 启发式审校",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python run.py --en en_us.json --zh zh_cn.json -o ./output/
  python run.py --en en_us.json --zh zh_cn.json -o ./output/ --no-llm
  python run.py --en en_us.json --zh zh_cn.json -o ./output/ --dry-run
        """,
    )

    parser.add_argument("--en", default=None, help="en_us.json 路径（传统模式必需）")
    parser.add_argument("--zh", default=None, help="zh_cn.json 路径（传统模式必需）")
    parser.add_argument("-o", "--output-dir", default="./output", help="输出目录")

    # PR 模式参数
    parser.add_argument("--pr", type=int, default=None,
                        help="PR 编号（PR 模式，--repo 可省略默认读配置）")
    parser.add_argument("--repo", default=None,
                        help="GitHub 仓库名，默认从配置读取")
    parser.add_argument("--token", default="",
                        help="GitHub Token（可选，公共仓库限流 60 req/hr）")
    parser.add_argument("--pr-alignment", default=None,
                        help="已保存的 PR 对齐 JSON 文件路径（跳过拉取步骤）")

    parser.add_argument("--no-llm", action="store_true",
                        help="跳过 LLM 审校")
    parser.add_argument("--interactive", action="store_true",
                        help="交互模式：逐条手动判定")
    parser.add_argument("--dry-run", action="store_true",
                        help="干运行：显示统计不调 LLM")
    parser.add_argument("--min-term-freq", type=int, default=3,
                        help="术语最低频次阈值")
    parser.add_argument("--fuzzy-threshold", type=float, default=60.0,
                        help="模糊搜索相似度阈值")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="LLM 每批条目数")
    parser.add_argument("--filter-only", action="store_true",
                        help="仅重跑 Phase 5 最终过滤（需已有 06_review_report.json）")

    args = parser.parse_args()

    # 参数互斥：传统模式 vs PR 模式
    is_traditional = bool(args.en and args.zh)
    is_pr = bool(args.pr)
    is_pr_alignment = bool(args.pr_alignment)

    if not is_traditional and not is_pr and not is_pr_alignment:
        parser.error("请提供 --en/--zh（传统模式）或 --pr（PR 模式）或 --pr-alignment")

    if is_pr:
        args.repo = args.repo or cfg.DEFAULT_PR_REPO

    if is_traditional:
        if not os.path.exists(args.en):
            print(f"错误: EN 文件不存在: {args.en}", file=sys.stderr)
            sys.exit(1)
        if not os.path.exists(args.zh):
            print(f"错误: ZH 文件不存在: {args.zh}", file=sys.stderr)
            sys.exit(1)

    # ── filter-only 模式：仅重跑 Phase 5 ──
    if args.filter_only:
        from pathlib import Path
        output_dir = Path(args.output_dir)
        review_path = output_dir / "06_review_report.json"
        if not review_path.exists():
            print(f"错误: 未找到 {review_path}，请先运行完整流水线", file=sys.stderr)
            sys.exit(1)
        import json as _json
        api_key = os.environ.get("REVIEW_OPENAI_API_KEY", "")
        if not api_key:
            print("错误: 未设置 REVIEW_OPENAI_API_KEY", file=sys.stderr)
            sys.exit(1)
        base_url = os.environ.get("REVIEW_OPENAI_BASE_URL", "https://api.deepseek.com")
        model = os.environ.get("REVIEW_OPENAI_MODEL", "deepseek-v4-flash")
        llm_call = create_openai_llm_call(api_key, model, base_url)

        from src.llm.llm_bridge import LLMBridge
        bridge = LLMBridge(llm_call)

        with open(review_path, "r", encoding="utf-8") as f:
            report = _json.load(f)

        verdicts = report.get("verdicts", [])
        total = report.get("stats", {}).get("total", len(verdicts))
        print(f"[Phase 5] 最终过滤: {len(verdicts)} 条 verdict")

        filtered, discard_records = bridge.filter_verdicts(verdicts)
        removed = len(discard_records)
        print(f"  驳回 {removed} 条, 保留 {len(filtered)} 条")

        # 保存驳回记录
        discard_path = output_dir / "07_filter_discards.json"
        with open(discard_path, "w", encoding="utf-8") as f:
            _json.dump(discard_records, f, ensure_ascii=False, indent=2)
        print(f"  驳回记录: {discard_path}")

        if removed > 0:
            stats = {
                "total": total,
                "PASS": total - len(filtered),
                "⚠️ SUGGEST": sum(1 for v in filtered if v.get("verdict") == "⚠️ SUGGEST"),
                "❌ FAIL": sum(1 for v in filtered if v.get("verdict") == "❌ FAIL"),
                "🔶 REVIEW": sum(1 for v in filtered if v.get("verdict") == "🔶 REVIEW"),
            }
            report["stats"] = stats
            report["verdicts"] = filtered
            with open(review_path, "w", encoding="utf-8") as f:
                _json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"  已更新: {review_path}")
        sys.exit(0)

    # ── PR 模式逻辑 ──
    pr_alignment: dict | None = None

    if is_pr_alignment:
        # 从文件加载已有的 PR 对齐数据
        print(f"[run.py] 加载 PR 对齐数据: {args.pr_alignment}")
        import json as _json_al
        with open(args.pr_alignment, "r", encoding="utf-8") as _f:
            pr_alignment = _json_al.load(_f)
        print(f"  已加载: {len(pr_alignment.get('all_entries', []))} 条变更, "
              f"{len(pr_alignment.get('all_warnings', []))} 条警告")

    elif is_pr:
        # 调用 PR 对齐器
        from src.tools.pr_aligner import run_pr_aligner
        align_output = run_pr_aligner(
            repo=args.repo,
            pr=args.pr,
            output_dir=args.output_dir,
            token=args.token,
        )
        import json as _json_al2
        with open(align_output, "r", encoding="utf-8") as _f:
            pr_alignment = _json_al2.load(_f)

    # ── 构建 LLM 调用 ──
    llm_call = None
    if not args.no_llm and not args.interactive and not args.dry_run:
        api_key = os.environ.get("REVIEW_OPENAI_API_KEY", "")
        if not api_key:
            print("警告: 未设置 REVIEW_OPENAI_API_KEY，将跳过 LLM 审校", file=sys.stderr)
        else:
            base_url = os.environ.get("REVIEW_OPENAI_BASE_URL", "https://api.deepseek.com")
            model = os.environ.get("REVIEW_OPENAI_MODEL", "deepseek-v4-flash")
            llm_call = create_openai_llm_call(api_key, model, base_url)

    pipeline = ReviewPipeline(
        en_path=args.en or "",
        zh_path=args.zh or "",
        output_dir=args.output_dir,
        llm_call=llm_call,
        no_llm=args.no_llm,
        interactive=args.interactive,
        dry_run=args.dry_run,
        min_term_freq=args.min_term_freq,
        fuzzy_threshold=args.fuzzy_threshold,
        batch_size=args.batch_size,
        pr_alignment=pr_alignment,
    )
    pipeline.run()


if __name__ == "__main__":
    main()
