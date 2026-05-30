from __future__ import annotations

"""核心领域数据模型 —— TypedDict + dataclass。

所有 dict 形状在此统一定义，禁止 Any 裸奔。
"""
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from src.dictionary.external import ExternalDictStore
    from src.dictionary.protocol import DictStore

# ═══════════════════════════════════════════════════════════
# 共享常量
# ═══════════════════════════════════════════════════════════

SourceType = Literal[
    "format_check", "terminology_check", "llm_review",
    "untranslated_review", "interactive", "pr_warning", "llm_error",
]
"""审校判决来源标识符。"""

SOURCE_FORMAT_CHECK: SourceType = "format_check"
SOURCE_TERMINOLOGY_CHECK: SourceType = "terminology_check"
SOURCE_LLM_REVIEW: SourceType = "llm_review"
SOURCE_UNTRANSLATED_REVIEW: SourceType = "untranslated_review"
SOURCE_INTERACTIVE: SourceType = "interactive"
SOURCE_PR_WARNING: SourceType = "pr_warning"
SOURCE_LLM_ERROR: SourceType = "llm_error"

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
    slug: str            # 模组标识符（PR 模式）
    _change: "ChangeDict"


class ChangeDict(TypedDict, total=False):
    """PR 模式条目附带的变更上下文。"""
    old_en: str
    old_zh: str
    ref_version: str
    ref_en: str
    ref_zh: str


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
    namespace: str
    version: str
    file_path: str
    slug: str


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


class VersionGroupData(TypedDict):
    """PR 模式中单版本的全量数据。"""
    version: str
    full_en: StrDict
    full_zh: StrDict
    entries: list[EntryDict]


class PRVersionGroups(TypedDict):
    """PR 模式按 slug 分组的版本数据。"""
    slug: str
    versions: list[str]           # 降序排列
    version_data: dict[str, VersionGroupData]
    cross_version_diffs: dict[str, Any]  # CrossVersionDiff 前向引用


class ManualFormatConfig(TypedDict):
    """manual_formats 中每个手册格式的配置。"""
    label: str
    dir_name: str


# ═══════════════════════════════════════════════════════════
# 辅助类型别名
# ═══════════════════════════════════════════════════════════

# {key: (full_en, full_zh)}
MultipartContext = dict[str, tuple[str, str]]

# {key: {"verdict": str, "diagnoses_str": str}}
AutoVerdictsMap = dict[str, dict[str, str]]

# {key: [fuzzy results]}
FuzzyResultsMap = dict[str, list[FuzzyResultDict]]

# {key: str}
StrDict = dict[str, str]

ManualFormatMap = dict[str, ManualFormatConfig]

# LLM 调用签名
LLMCallable = Callable[[str], str]


def normalize_verdict_field(val: object) -> str:
    """将任意值规范化为字符串——dict→json, 非str→str。"""
    import json as _json
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        zh = val.get("zh") or val.get("text") or val.get("value") or ""
        return zh if isinstance(zh, str) and zh else _json.dumps(val, ensure_ascii=False)
    return str(val) if val is not None else ""


def normalize_verdict(v: Mapping, *, fields: tuple[str, ...] | None = None) -> dict:
    """规范化 verdict dict 的所有文本字段类型。

    默认规范化 VerdictDict 的 11 个已知字段。
    传 fields 参数可按需限制字段集合。
    """
    import json as _json
    if fields is None:
        fields = ("key", "en_current", "zh_current", "verdict", "suggestion",
                   "reason", "source", "namespace", "version", "file_path")
    result: dict[str, str] = {}
    for f in fields:
        result[f] = normalize_verdict_field(v.get(f, ""))
    # Carry over any extra keys verbatim (type-safe use only)
    for k, val in v.items():
        if k not in result:
            result[k] = val if isinstance(val, str) else str(val)
    return result

# ═══════════════════════════════════════════════════════════
# Verdict 枚举
# ═══════════════════════════════════════════════════════════

VERDICT_PASS    = "PASS"
VERDICT_SUGGEST = "⚠️ SUGGEST"
VERDICT_REVIEW  = "🔶 REVIEW"
VERDICT_FAIL    = "❌ FAIL"

# ── 整数 verdict（DB 存储格式）──
# Display（报告/控制台）—— 带 emoji
# LLM（提示词/LLM 响应）—— 不带 emoji

VERDICT_DISPLAY_TO_INT: dict[str, int] = {
    "PASS": 0,
    "⚠️ SUGGEST": 1,
    "🔶 REVIEW": 2,
    "❌ FAIL": 3,
}

VERDICT_INT_TO_DISPLAY: dict[int, str] = {
    0: "PASS",
    1: "⚠️ SUGGEST",
    2: "🔶 REVIEW",
    3: "❌ FAIL",
}

VERDICT_LLM_TO_INT: dict[str, int] = {
    "PASS": 0,
    "SUGGEST": 1,
    "REVIEW": 2,
    "FAIL": 3,
}

VERDICT_INT_TO_LLM: dict[int, str] = {
    0: "PASS",
    1: "SUGGEST",
    2: "REVIEW",
    3: "FAIL",
}

# 向后兼容别名
VERDICT_STR_TO_INT = VERDICT_DISPLAY_TO_INT
VERDICT_INT_TO_STR = VERDICT_INT_TO_DISPLAY


def verdict_str_to_int(s: str) -> int:
    """字符串 verdict → 整数。

    匹配策略：精确匹配（display + LLM 两套）→ 大小写不敏感关键词 fallback。
    无法识别时抛出 ValueError（防止 LLM 输出畸变被静默当作 PASS）。
    """
    s = s.strip()
    # 1. 精确匹配 — 同时查 display 和 LLM 映射
    if s in VERDICT_DISPLAY_TO_INT:
        return VERDICT_DISPLAY_TO_INT[s]
    if s in VERDICT_LLM_TO_INT:
        return VERDICT_LLM_TO_INT[s]
    # 2. 大小写不敏感关键词 fallback
    lower = s.lower()
    if "fail" in lower:
        return 3
    if "review" in lower:
        return 2
    if "suggest" in lower:
        return 1
    if "pass" in lower:
        return 0
    raise ValueError(
        f"无法识别的 verdict 字符串: {s!r}，"
        f"期望 PASS / SUGGEST / REVIEW / FAIL 或其 emoji 变体"
    )


def verdict_int_to_str(i: int, *, llm: bool = False) -> str:
    """整数 verdict → 字符串。

    llm=False（默认）返回带 emoji 的展示字符串；llm=True 返回纯文本供 LLM 消费。
    非法输入抛出 ValueError。
    """
    mapping = VERDICT_INT_TO_LLM if llm else VERDICT_INT_TO_DISPLAY
    if i in mapping:
        return mapping[i]
    raise ValueError(f"无效的 verdict 整数: {i}，有效范围 0-3")


def _format_diagnoses(diagnoses_raw: str) -> str:
    """从 diagnoses JSON 数组格式化诊断文本。

    过滤非空 reason，每项格式化为 `[source] reason`，去重后 `; ` join。
    """
    import json as _json
    try:
        diags = _json.loads(diagnoses_raw)
    except (_json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(diags, list):
        return ""
    seen: set[str] = set()
    parts: list[str] = []
    for d in diags:
        if not isinstance(d, dict):
            continue
        reason = (d.get("reason") or "").strip()
        if not reason:
            continue
        source = (d.get("source") or "unknown").strip()
        formatted = f"[{source}] {reason}"
        if formatted not in seen:
            seen.add(formatted)
            parts.append(formatted)
    return "; ".join(parts)


def merge_diagnoses_for_report(diagnoses_raw: str) -> str:
    """合并诊断为一条自然段落（用于最终报告输出）。

    策略：
    - 优先取 llm_review 的 reason（LLM 已在 prompt 中看到自动检查结果，应已整合）
    - 无 llm_review 时，拼接所有非空 reason（去掉 [source] 标签），去重后用中文分号连接
    """
    import json as _json
    try:
        diags = _json.loads(diagnoses_raw)
    except (_json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(diags, list):
        return ""

    llm_reason = ""
    other_reasons: list[str] = []
    seen: set[str] = set()

    for d in diags:
        if not isinstance(d, dict):
            continue
        reason = (d.get("reason") or "").strip()
        if not reason:
            continue
        # 去重（同一内容的诊断只取一条）
        if reason in seen:
            continue
        seen.add(reason)

        source = (d.get("source") or "unknown").strip()
        if source == "llm_review":
            llm_reason = reason
        else:
            other_reasons.append(reason)

    # 优先返回 LLM 的 reason（已经是自然语言段落）
    if llm_reason:
        return llm_reason

    # 无 LLM 时：去掉 [source] 标签后拼接
    return "；".join(other_reasons) if other_reasons else ""


def update_diagnosis(db: Any, key: str, source: str, reason: str) -> str:
    """读取 entries 表中 key 的 diagnoses，按 source 替换/追加，返回 JSON 字符串。

    调用方将此返回值用于 UPDATE 语句中的 diagnoses=? 参数。
    """
    import json as _json
    row = db.execute("SELECT diagnoses FROM entries WHERE key=?", (key,)).fetchone()
    if row:
        try:
            diagnoses = _json.loads(row["diagnoses"])
        except (_json.JSONDecodeError, TypeError):
            diagnoses = []
    else:
        diagnoses = []
    existing_idx = next(
        (i for i, d in enumerate(diagnoses) if isinstance(d, dict) and d.get("source") == source),
        None,
    )
    new_diag = {"source": source, "reason": reason}
    if existing_idx is not None:
        diagnoses[existing_idx] = new_diag
    else:
        diagnoses.append(new_diag)
    return _json.dumps(diagnoses, ensure_ascii=False)


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
    batch_size: int = 0

    # ── PR 模式 ──
    pr_mode: bool = False
    pr_alignment: PRAlignmentWrapper | None = None
    pr_change_meta: dict[str, PRChangeMetaDict] = field(default_factory=dict)
    pr_warnings: list[PRWarningDict] = field(default_factory=list)
    zh_only_entries: list[PRAlignmentEntryDict] = field(default_factory=list)
    pr_full_en_data: StrDict = field(default_factory=dict)
    pr_full_zh_data: StrDict = field(default_factory=dict)
    pr_version_groups: dict[str, PRVersionGroups] = field(default_factory=dict)
    pr_combined_full_en: StrDict = field(default_factory=dict)
    pr_combined_full_zh: StrDict = field(default_factory=dict)

    # ── 中间结果 ──
    en_data: StrDict = field(default_factory=dict)
    zh_data: StrDict = field(default_factory=dict)
    alignment: AlignmentDict = field(default_factory=dict)

    glossary: list[GlossaryDict] = field(default_factory=list)

    fuzzy_results_map: FuzzyResultsMap = field(default_factory=dict)

    dict_stores: list[DictStore] = field(default_factory=list)
    external_dict_store: ExternalDictStore | None = None

    config: dict[str, Any] = field(default_factory=dict)

    # ── DB 连接 ──
    db: Any | None = None  # PipelineDB (lazy import to avoid circular)

    def ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def alignment_entries(self) -> list[EntryDict]:
        return self.alignment.get("matched_entries", [])

    def auto_verdicts_map(self) -> AutoVerdictsMap:
        """从 entries 表查询有诊断的条目，返回 {key: {verdict, diagnoses_str}}。

        diagnoses_str 格式为 `[source] reason; [source] reason`，供 LLM prompt 直接消费。
        """
        import json as _json
        m: AutoVerdictsMap = {}
        if self.db is None:
            return m
        rows = self.db.execute(
            "SELECT key, verdict, diagnoses FROM entries WHERE diagnoses != '[]'"
        ).fetchall()
        for r in rows:
            diag_str = _format_diagnoses(r["diagnoses"])
            if not diag_str:
                continue
            m[r["key"]] = {
                "verdict": verdict_int_to_str(r["verdict"], llm=True),
                "diagnoses_str": diag_str,
            }
        return m
