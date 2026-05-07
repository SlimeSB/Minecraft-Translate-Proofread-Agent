"""Minecraft 模组翻译审校工具 — CLI 入口。

用法:
    python run.py --en en_us.json --zh zh_cn.json -o ./output/
    python run.py --en en_us.json --zh zh_cn.json -o ./output/ --dry-run
    python run.py --en en_us.json --zh zh_cn.json -o ./output/ --no-llm
    python run.py --en en_us.json --zh zh_cn.json -o ./output/ --interactive

LLM 配置（通过 .env 或环境变量）:
    REVIEW_OPENAI_API_KEY    必需，OpenAI 兼容 API key（DeepSeek 等）
    REVIEW_OPENAI_BASE_URL   可选，默认 https://api.deepseek.com
    REVIEW_OPENAI_MODEL      可选，默认 deepseek-v4-flash
    GITHUB_TOKEN             可选，GitHub API Token（避免限流）
"""
import argparse
import json
import os
import sys
from pathlib import Path

from src.cli import load_dotenv, configure_utf8_output, safe_print, check_api_health
from src.llm.client import create_openai_llm_call
from src.models import PipelineContext, PRAlignmentWrapper
from src.pipeline.pipeline import ReviewPipeline
from src.pipeline.phase4_filter import run_phase4
from src.pipeline.phase5_report import run_phase5
from src.storage.database import PipelineDB
from src import config as cfg

load_dotenv()
configure_utf8_output()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minecraft 模组翻译审校流水线 — 自动检查 + LLM 启发式审校",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python run.py --en en_us.json --zh zh_cn.json -o ./output/\n"
               "  python run.py --en en_us.json --zh zh_cn.json -o ./output/ --no-llm\n"
               "  python run.py --en en_us.json --zh zh_cn.json -o ./output/ --dry-run",
    )

    _add_arguments(parser)
    args = parser.parse_args()

    # ── 模式验证 ──
    is_traditional = bool(args.en and args.zh)
    is_pr = bool(args.pr)
    is_pr_alignment = bool(args.pr_alignment)

    if not is_traditional and not is_pr and not is_pr_alignment:
        parser.error("请提供 --en/--zh（传统模式）或 --pr（PR 模式）或 --pr-alignment")

    if is_pr:
        args.repo = args.repo or cfg.DEFAULT_PR_REPO

    if is_traditional:
        _validate_input_files(args.en, args.zh)

    # ── 输出目录 ──
    output_dir = args.output_dir
    if is_pr:
        output_dir = str(Path(args.output_dir) / f"pr{args.pr}")

    # ── filter-only 模式 ──
    if args.filter_only:
        _run_filter_only(args, output_dir)
        return

    # ── PR 对齐 ──
    pr_alignment = _load_pr_alignment(args, is_pr, is_pr_alignment, output_dir)

    # ── 构建 LLM ──
    llm_call, filter_llm_call = _build_llm_calls(args)

    # ── 运行流水线 ──
    pipeline = ReviewPipeline(
        en_path=args.en or "",
        zh_path=args.zh or "",
        output_dir=output_dir,
        llm_call=llm_call,
        filter_llm_call=filter_llm_call,
        no_llm=args.no_llm,
        interactive=args.interactive,
        dry_run=args.dry_run,
        min_term_freq=args.min_term_freq,
        fuzzy_threshold=args.fuzzy_threshold,
        batch_size=args.batch_size,
        pr_alignment=pr_alignment,
    )
    pipeline.run()


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--en", default=None, help="en_us.json 路径（传统模式必需）")
    parser.add_argument("--zh", default=None, help="zh_cn.json 路径（传统模式必需）")
    parser.add_argument("-o", "--output-dir", default="./output", help="输出目录")
    parser.add_argument("--pr", type=int, default=None, help="PR 编号（PR 模式）")
    parser.add_argument("--repo", default=None, help="GitHub 仓库名，默认从配置读取")
    parser.add_argument("--token", default=None, help="GitHub Token")
    parser.add_argument("--pr-alignment", default=None, help="已保存的 PR 对齐 JSON 路径")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 审校")
    parser.add_argument("--interactive", action="store_true", help="交互模式：逐条手动判定")
    parser.add_argument("--dry-run", action="store_true", help="干运行：显示统计不调 LLM")
    parser.add_argument("--min-term-freq", type=int, default=3, help="术语最低频次阈值")
    parser.add_argument("--fuzzy-threshold", type=float, default=60.0, help="模糊搜索相似度阈值")
    parser.add_argument("--batch-size", type=int, default=20, help="LLM 每批条目数")
    parser.add_argument("--filter-only", action="store_true",
                        help="仅重跑 Phase 4 最终过滤 + Phase 5 报告（需已有 pipeline.db）")


def _validate_input_files(en_path: str, zh_path: str) -> None:
    if not os.path.exists(en_path):
        print(f"错误: EN 文件不存在: {en_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(zh_path):
        print(f"错误: ZH 文件不存在: {zh_path}", file=sys.stderr)
        sys.exit(1)


def _run_filter_only(args, output_dir_str: str) -> None:
    output_dir = Path(output_dir_str)
    db_path = output_dir / "pipeline.db"
    if not db_path.exists():
        print(f"错误: 未找到 {db_path}，请先运行完整流水线", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("REVIEW_OPENAI_API_KEY", "")
    if not api_key:
        print("错误: 未设置 REVIEW_OPENAI_API_KEY", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("REVIEW_OPENAI_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("REVIEW_OPENAI_MODEL", "deepseek-v4-flash")
    llm_call = create_openai_llm_call(api_key, model, base_url)
    filter_llm_call = create_openai_llm_call(api_key, model, base_url, log_dir="logs/filter")

    db = PipelineDB(db_path)
    verdicts = db.load_verdicts(phase="merged", filtered=0)
    alignment = db.load_alignment()
    db.close()

    if not verdicts:
        print("无待过滤 verdict")
        sys.exit(0)

    ctx = PipelineContext(
        output_dir=output_dir,
        llm_call=llm_call,
        filter_llm_call=filter_llm_call,
    )
    ctx.alignment = alignment

    run_phase4(ctx)
    run_phase5(ctx)


def _load_pr_alignment(args, is_pr: bool, is_pr_alignment: bool, output_dir: str) -> PRAlignmentWrapper | None:
    if is_pr_alignment:
        print(f"[run.py] 加载 PR 对齐数据: {args.pr_alignment}")
        with open(args.pr_alignment, "r", encoding="utf-8") as f:
            pr_alignment = json.load(f)
        print(f"  已加载: {len(pr_alignment.get('all_entries', []))} 条变更, "
              f"{len(pr_alignment.get('all_warnings', []))} 条警告")
        return pr_alignment

    if is_pr:
        from src.tools.pr import run_pr_aligner
        github_token = args.token or os.environ.get("GITHUB_TOKEN", "")
        align_output = run_pr_aligner(
            repo=args.repo,
            pr=args.pr,
            output_dir=output_dir,
            token=github_token,
        )
        with open(align_output, "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def _build_llm_calls(args) -> tuple:
    llm_call = None
    filter_llm_call = None

    if args.no_llm or args.interactive or args.dry_run:
        return llm_call, filter_llm_call

    api_key = os.environ.get("REVIEW_OPENAI_API_KEY", "")
    base_url = os.environ.get("REVIEW_OPENAI_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("REVIEW_OPENAI_MODEL", "deepseek-v4-flash")

    if not api_key:
        print("警告: 未设置 REVIEW_OPENAI_API_KEY，将跳过 LLM 审校", file=sys.stderr)
        return llm_call, filter_llm_call

    print(f"[Pre-flight] 检查 API: {base_url} (模型: {model})")
    if not check_api_health(base_url, api_key):
        print("  提示: 可设置 REVIEW_OPENAI_BASE_URL / REVIEW_OPENAI_MODEL 更换端点", file=sys.stderr)
        print("  将继续运行，但 LLM 调用可能失败", file=sys.stderr)

    llm_call = create_openai_llm_call(api_key, model, base_url,
                                      system_prompt=cfg.REVIEW_SYSTEM_PROMPT)
    filter_llm_call = create_openai_llm_call(api_key, model, base_url,
                                              system_prompt=cfg.REVIEW_SYSTEM_PROMPT,
                                              log_dir="logs/filter")
    return llm_call, filter_llm_call


if __name__ == "__main__":
    main()
