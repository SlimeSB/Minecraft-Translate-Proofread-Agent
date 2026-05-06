"""核心领域数据模型。

所有 Phase 通过 PipelineContext 传递数据，不再用 God Object 的 self.* 杂糅。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ── Verdict 枚举 ───────────────────────────────────────────
VERDICT_PASS    = "PASS"
VERDICT_SUGGEST = "⚠️ SUGGEST"
VERDICT_REVIEW  = "🔶 REVIEW"
VERDICT_FAIL    = "❌ FAIL"

VERDICT_PRIORITY: dict[str, int] = {
    VERDICT_FAIL:    4,
    VERDICT_REVIEW:  3,
    VERDICT_SUGGEST: 2,
    VERDICT_PASS:    1,
}

ALL_VERDICTS = frozenset([VERDICT_PASS, VERDICT_SUGGEST, VERDICT_REVIEW, VERDICT_FAIL])

# ── 术语条目 ────────────────────────────────────────────────

@dataclass
class GlossaryEntry:
    en: str
    zh: str

# ── 审校判决 ────────────────────────────────────────────────

@dataclass
class Verdict:
    key: str
    verdict: str                      # PASS / ⚠️ SUGGEST / 🔶 REVIEW / ❌ FAIL
    reason: str = ""
    suggestion: str = ""
    en_current: str = ""
    zh_current: str = ""
    source: str = ""                  # "format_check" | "terminology_check" | "llm_review" | "interactive" | "pr_warning" | "llm_error"


# ── 管道上下文 ─────────────────────────────────────────────

@dataclass
class PipelineContext:
    """贯穿所有 Pipeline Phase 的共享上下文。

    每个 Phase 是接收 ctx、修改 ctx 的纯函数，
    Pipeline 编排器只管顺序调用。
    """

    # ── 输入 ──
    en_path: Path | None = None
    zh_path: Path | None = None
    output_dir: Path = Path("./output")

    # ── LLM 回调 ──
    llm_call: Callable[[str], str] | None = None
    filter_llm_call: Callable[[str], str] | None = None  # Phase 5 用，独立 system_prompt

    # ── 运行选项 ──
    no_llm: bool = False
    interactive: bool = False
    dry_run: bool = False
    min_term_freq: int = 3
    fuzzy_threshold: float = 60.0
    fuzzy_top: int = 5
    batch_size: int = 20

    # ── PR 模式 ──
    pr_mode: bool = False
    pr_alignment: dict[str, Any] | None = None
    pr_change_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    pr_warnings: list[dict[str, Any]] = field(default_factory=list)
    zh_only_entries: list[dict[str, Any]] = field(default_factory=list)

    # ── 中间结果 ──
    en_data: dict[str, str] = field(default_factory=dict)
    zh_data: dict[str, str] = field(default_factory=dict)
    alignment: dict[str, Any] = field(default_factory=dict)

    glossary: list[dict[str, Any]] = field(default_factory=list)

    format_verdicts: list[dict[str, Any]] = field(default_factory=list)
    term_verdicts: list[dict[str, Any]] = field(default_factory=list)
    llm_verdicts: list[dict[str, Any]] = field(default_factory=list)

    fuzzy_results_map: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def alignment_entries(self) -> list[dict[str, Any]]:
        return self.alignment.get("matched_entries", [])

    def auto_verdicts_map(self) -> dict[str, list[dict[str, Any]]]:
        m: dict[str, list[dict[str, Any]]] = {}
        for v in self.format_verdicts + self.term_verdicts:
            k = v.get("key", "")
            if k:
                m.setdefault(k, []).append(v)
        return m
