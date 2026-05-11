"""核心领域数据模型 —— TypedDict + dataclass。

所有 dict 形状在此统一定义，禁止 Any 裸奔。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypedDict

# ═══════════════════════════════════════════════════════════
# TypedDict — 领域字典形状
# ═══════════════════════════════════════════════════════════


class EntryDict(TypedDict, total=False):
    """对齐条目。Phase 1 产出，贯穿全管道。"""
    key: str
    en: str
    zh: str
    format: str         # "json" | "lang" | "guideme"
    namespace: str       # PR 模式
    version: str
    file_path: str
    _change: "ChangeDict"


class ChangeDict(TypedDict, total=False):
    """PR 模式条目附带的变更上下文。"""
    old_en: str
    old_zh: str


class MissingEntryDict(TypedDict):
    """EN 有但 ZH 无的条目。"""
    key: str
    en: str


class ExtraEntryDict(TypedDict):
    """ZH 有但 EN 无的条目。"""
    key: str
    zh: str


class SuspiciousEntryDict(TypedDict):
    """疑似未翻译条目。"""
    key: str
    en: str
    zh: str
    reason: str


class AlignmentStats(TypedDict):
    matched: int
    missing_zh: int
    extra_zh: int
    suspicious_untranslated: int
    total_en: int
    total_zh: int


class AlignmentDict(TypedDict, total=False):
    """键对齐结果。Phase 1 产出。"""
    matched_entries: list[EntryDict]
    missing_zh: list[MissingEntryDict]
    extra_zh: list[ExtraEntryDict]
    suspicious_untranslated: list[SuspiciousEntryDict]
    stats: AlignmentStats


class VerdictDict(TypedDict, total=False):
    """审校判决。Phase 3a/2/3c 产出，Phase 4/5 消费。"""
    key: str
    en_current: str
    zh_current: str
    verdict: str        # "PASS" | "⚠️ SUGGEST" | "🔶 REVIEW" | "❌ FAIL"
    suggestion: str
    reason: str
    source: str          # "format_check" | "terminology_check" | "llm_review" | "interactive" | "pr_warning" | "llm_error"
    version: str
    file_path: str


class GlossaryDict(TypedDict):
    """术语表条目。"""
    en: str
    zh: str


class FuzzyResultDict(TypedDict):
    """模糊搜索结果。"""
    similarity: float
    key: str
    en: str
    zh: str


class PRAlignmentEntryDict(TypedDict, total=False):
    """PR 对齐条目（来自 GitHub PR diff）。"""
    key: str
    en: str
    zh: str
    namespace: str
    format: str
    version: str
    file_path: str
    old_en: str
    old_zh: str
    review_type: str     # "normal" | "en_changed_zh_unchanged" | "zh_only_change"


class PRAlignmentWrapper(TypedDict):
    """PR 对齐数据整体结构。"""
    all_entries: list[PRAlignmentEntryDict]
    all_warnings: list["PRWarningDict"]


class PRWarningDict(TypedDict):
    """PR 警告。"""
    key: str


class PRChangeMetaDict(TypedDict):
    """PR 变更元信息。"""
    en_changed: bool
    zh_changed: bool
    old_en: str
    old_zh: str
    warning: bool
    review_type: str
    version: str


class ReviewStatsDict(TypedDict):
    total: int
    PASS: int
    SUGGEST: int      # ⚠️ SUGGEST
    FAIL: int          # ❌ FAIL
    REVIEW: int        # 🔶 REVIEW


class ReviewReportDict(TypedDict):
    """审校报告（pipeline.db verdicts 表 phase='merged'）。"""
    stats: ReviewStatsDict
    verdicts: list[VerdictDict]


class FilterDiscardRecord(TypedDict):
    """Phase 5 过滤驳回记录。"""
    key: str
    reason: str


class KeyPrefixConfig(TypedDict, total=False):
    """key_prefixes 中每个前缀的配置。"""
    label: str
    focus: str
    llm_required: bool


# ═══════════════════════════════════════════════════════════
# 辅助类型别名
# ═══════════════════════════════════════════════════════════

# {prefix: [entries]}
GroupedEntries = dict[str, list[EntryDict]]

# {key: (full_en, full_zh)}
MultipartContext = dict[str, tuple[str, str]]

# {key: [verdicts]}
AutoVerdictsMap = dict[str, list[VerdictDict]]

# {key: [fuzzy results]}
FuzzyResultsMap = dict[str, list[FuzzyResultDict]]

# {key: str}
StrDict = dict[str, str]

# {prefix: config}
KeyPrefixMap = dict[str, KeyPrefixConfig]

# LLM 调用签名
LLMCallable = Callable[[str], str]

# ═══════════════════════════════════════════════════════════
# Verdict 枚举
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# 管道上下文 (dataclass)
# ═══════════════════════════════════════════════════════════


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
    llm_call: LLMCallable | None = None
    filter_llm_call: LLMCallable | None = None

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
    pr_alignment: PRAlignmentWrapper | None = None
    pr_change_meta: dict[str, PRChangeMetaDict] = field(default_factory=dict)
    pr_warnings: list[PRWarningDict] = field(default_factory=list)
    zh_only_entries: list[PRAlignmentEntryDict] = field(default_factory=list)
    pr_full_en_data: StrDict = field(default_factory=dict)
    pr_full_zh_data: StrDict = field(default_factory=dict)

    # ── 中间结果 ──
    en_data: StrDict = field(default_factory=dict)
    zh_data: StrDict = field(default_factory=dict)
    alignment: AlignmentDict = field(default_factory=dict)

    glossary: list[GlossaryDict] = field(default_factory=list)

    format_verdicts: list[VerdictDict] = field(default_factory=list)
    term_verdicts: list[VerdictDict] = field(default_factory=list)
    llm_verdicts: list[VerdictDict] = field(default_factory=list)

    fuzzy_results_map: FuzzyResultsMap = field(default_factory=dict)

    dict_stores: list = field(default_factory=list)  # list[DictStore]
    external_dict_store: object = None  # ExternalDictStore | None (保留别名)

    config: dict = field(default_factory=dict)

    filter_cache_hits: int = 0
    filter_cache_total: int = 0

    def ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def alignment_entries(self) -> list[EntryDict]:
        return self.alignment.get("matched_entries", [])

    def auto_verdicts_map(self) -> AutoVerdictsMap:
        m: AutoVerdictsMap = {}
        for v in self.format_verdicts + self.term_verdicts:
            k = v.get("key", "")
            if k:
                m.setdefault(k, []).append(v)
        return m
