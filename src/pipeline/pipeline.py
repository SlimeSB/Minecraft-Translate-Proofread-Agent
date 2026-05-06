"""Minecraft 模组翻译审校流水线 —— 薄编排器。

只负责按顺序调用各 Phase，状态全部通过 PipelineContext 传递。
"""
import sys
from pathlib import Path

from src.models import LLMCallable, PipelineContext, PRAlignmentWrapper
from src.pipeline.phase1_alignment import run_phase1
from src.pipeline.phase2_terminology import run_phase2
from src.pipeline.phase3a_format import run_phase3a
from src.pipeline.phase3c_review import run_phase3c
from src.pipeline.phase4_report import run_phase4
from src.pipeline.phase5_filter import run_phase5


class ReviewPipeline:
    """翻译审校流水线 — 薄编排层。

    所有 Phase 逻辑在独立模块中，通过 PipelineContext 传递状态。
    """

    def __init__(
        self,
        en_path: str = "",
        zh_path: str = "",
        output_dir: str = "./output",
        *,
        llm_call: LLMCallable | None = None,
        filter_llm_call: LLMCallable | None = None,
        no_llm: bool = False,
        interactive: bool = False,
        dry_run: bool = False,
        min_term_freq: int = 3,
        fuzzy_threshold: float = 60.0,
        fuzzy_top: int = 5,
        batch_size: int = 20,
        pr_alignment: PRAlignmentWrapper | None = None,
    ):
        self.ctx = PipelineContext(
            en_path=Path(en_path) if en_path else None,
            zh_path=Path(zh_path) if zh_path else None,
            output_dir=Path(output_dir),
            llm_call=llm_call,
            filter_llm_call=filter_llm_call,
            no_llm=no_llm,
            interactive=interactive,
            dry_run=dry_run,
            min_term_freq=min_term_freq,
            fuzzy_threshold=fuzzy_threshold,
            fuzzy_top=fuzzy_top,
            batch_size=batch_size,
            pr_mode=pr_alignment is not None,
            pr_alignment=pr_alignment,
        )
        self.ctx.ensure_output_dir()

    def run(self) -> None:
        ctx = self.ctx
        print(f"{'='*60}")
        print("Minecraft 模组翻译审校流水线")
        print(f"  EN: {ctx.en_path}")
        print(f"  ZH: {ctx.zh_path}")
        print(f"  输出: {ctx.output_dir}")
        if ctx.dry_run:
            print("  模式: 干运行")
        elif ctx.interactive:
            print("  模式: 交互审校")
        elif ctx.no_llm:
            print("  模式: 仅自动检查")
        print(f"{'='*60}")

        try:
            run_phase1(ctx)       # 键对齐 / PR 数据加载
            run_phase2(ctx)       # 术语提取与一致性检查
            run_phase3a(ctx)      # 全自动格式检查
            run_phase3c(ctx)      # LLM 审校（含筛选 + 模糊搜索）
            run_phase4(ctx)       # 报告生成
            run_phase5(ctx)       # 最终 LLM 过滤
        except Exception as e:
            print(f"\n错误: {e}", file=sys.stderr)
            raise
