"""
全自动格式验证器：对每条 aligned entry 执行结构化格式检查。
所有检查均为确定性规则，无需 LLM 参与。

用法:
    from format_checker import FormatChecker
    checker = FormatChecker()
    verdicts = checker.check_all(matched_entries)
"""
import json
import re
from typing import Any

from src import config as cfg

# ═══════════════════════════════════════════════════════════
# 正则模式库
# ═══════════════════════════════════════════════════════════

# printf 风格占位符: %d, %s, %f, %1$s, %2$d, %.2f, %+d 等
RE_PRINTF = re.compile(r"%[+\-]?\d*\.?\d*[dsf]")
RE_POSITIONAL_PRINTF = re.compile(r"%\d+\$[dsf]")
# 归一化: %1$s → %s 用于比较
def _normalize_printf(p: str) -> str:
    m = RE_POSITIONAL_PRINTF.match(p)
    if m:
        return "%" + p[-1]
    return p
# 其他占位符风格: %msg%, %key% (仅 ASCII 标识符)
RE_PERCENT_VAR = re.compile(r"%[A-Za-z_]\w*%", re.ASCII)
RE_BRACE_VAR = re.compile(r"\{(\d+|[a-zA-Z_]\w*)\}")

# Minecraft 格式码: §[0-9a-fk-or]
RE_MC_COLOR = re.compile(r"§[0-9a-fA-Fk-oK-OrR]")
# 备用格式码: &[0-9a-f]
RE_ALT_COLOR = re.compile(r"&[0-9a-fA-F]")

# 动作占位符: $(l:...) 和 $(action)
RE_PLACEHOLDER_DOLLAR = re.compile(r"\$\((?:l:[^)]*|[a-zA-Z_]\w*)\)")

# HTML/XML 标签
RE_HTML_TAG = re.compile(r"</?[a-zA-Z_]\w*(?:\s[^>]*)?/?>")

# 换行标记: <br>, \n, \\n
RE_BR_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
RE_NEWLINE = re.compile(r"\\n|\n")

# 能量/体积单位（\b 需 re.ASCII，否则中文被当作 \w 导致边界失效）
RE_ENERGY_UNIT = re.compile(r"\b(FE|RF|MB|EU|AE|kJ|kW|kRF)\b", re.ASCII)

# 中文全角标点
RE_CHINESE_PUNCT = re.compile(r"[，。；：？！、‘’“”【】《》（）—…]")

# 中文内容检测（含中文字符）
RE_CHINESE_CHAR = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# 省略号检测
RE_ELLIPSIS_WRONG = re.compile(r"\.{3}")  # 三个英文句号 ...
RE_ELLIPSIS_BOTTOM = re.compile(r"……")    # 偏下省略号
RE_ELLIPSIS_CENTER = re.compile(r"⋯⋯")    # 居中省略号（正确）

# tellraw JSON 检测：以 {"text": 开头的字符串
RE_TELLRAW = re.compile(r'^\s*\{[^}]*"text"\s*:')

# 非代码/非专有名词的英文标记（用于判断 en==zh 是否合理）
NON_TRANSLATABLE_PATTERNS = [
    re.compile(r"^[A-Z_]+$"),           # 全大写下划线常量
    re.compile(r"^[0-9]+$"),            # 纯数字
    re.compile(r"^[A-Za-z0-9_.-]+$"),   # 纯ASCII标识符
    re.compile(r"^§[0-9a-fA-F].*"),     # 格式码开头
]


def count_pattern(text: str, pattern: re.Pattern) -> int:
    """统计 pattern 在 text 中的出现次数。"""
    return len(pattern.findall(text))


def is_likely_code_or_proper_noun(text: str) -> bool:
    """判断文本是否看起来像代码/专有名词/标识符（不需要翻译的那种）。"""
    for pat in NON_TRANSLATABLE_PATTERNS:
        if pat.match(text.strip()):
            return True
    return False


def is_tellraw_json(text: str) -> bool:
    """判断 value 是否为 tellraw JSON 字符串。"""
    return bool(RE_TELLRAW.search(text.strip()))


def is_chinese_text(text: str) -> bool:
    """判断文本是否包含中文。"""
    return bool(RE_CHINESE_CHAR.search(text))


# ═══════════════════════════════════════════════════════════
# 格式检查器
# ═══════════════════════════════════════════════════════════

class FormatChecker:
    """对单条翻译条目执行所有格式检查。"""

    def __init__(self, tree_terms: set[str] | None = None):
        """
        :param tree_terms: 木材/树木相关术语集合，用于树名检查
        """
        self.tree_terms = tree_terms or {
            "log", "wood", "planks", "sapling", "leaves",
            "stairs", "slab", "fence", "fence_gate", "door",
            "sign", "boat", "chest_boat", "button", "pressure_plate",
            "trapdoor", "stripped_log", "stripped_wood",
        }

    def check_all(self, entry: dict[str, str]) -> list[dict[str, Any]]:
        """对单条 entry 执行所有格式检查，返回 verdict 列表。"""
        key = entry["key"]
        en = entry["en"]
        zh = entry["zh"]

        checks = [
            self._check_empty_translation,
            self._check_music_disc_no_translation,
            self._check_placeholder_integrity,
            self._check_special_tags,
            self._check_tellraw_json,
            self._check_punctuation,
            self._check_trailing_whitespace,
            self._check_energy_units,
            self._check_ellipsis,
            self._check_sound_subtitle_format,
            self._check_tree_terms,
        ]

        verdicts: list[dict[str, Any]] = []
        for check_fn in checks:
            result = check_fn(key, en, zh)
            if result:
                verdicts.append(result)
        return verdicts

    # ── 各检查方法 ───────────────────────────────────────

    def _check_empty_translation(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查空翻译：zh == en 且原文非代码/专有名词。"""
        if en == zh and en != "":
            if "music_disc" in key and key.endswith(".desc"):
                return None  # 唱片名(.desc)不翻译
            if not is_likely_code_or_proper_noun(en):
                return self._verdict(key, en, zh, "❌ FAIL",
                    reason=f"值相同（'{en[:60]}'），疑似未翻译",
                )
        return None

    def _check_music_disc_no_translation(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """唱片名(.desc)不应翻译，已翻译则回报。"""
        if "music_disc" in key and key.endswith(".desc") and en != zh and en != "" and zh != "":
            return self._verdict(key, en, zh, "⚠️ SUGGEST",
                reason=f"唱片名不应翻译，建议保留原文（'{en[:60]}'）",
            )
        return None

    def _check_placeholder_integrity(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查占位符完整性：%d, %s, %f, %n$s, %msg%, {0} 等。"""
        issues: list[str] = []

        # printf 占位符 (归一化: %1$s → %s)
        en_printf = [_normalize_printf(p) for p in
                     RE_PRINTF.findall(en) + RE_POSITIONAL_PRINTF.findall(en)]
        zh_printf = [_normalize_printf(p) for p in
                     RE_PRINTF.findall(zh) + RE_POSITIONAL_PRINTF.findall(zh)]
        if sorted(en_printf) != sorted(zh_printf):
            en_count = {p: en_printf.count(p) for p in set(en_printf)}
            zh_count = {p: zh_printf.count(p) for p in set(zh_printf)}
            missing_en = [p for p in en_count if en_count.get(p, 0) > zh_count.get(p, 0)]
            missing_zh = [p for p in zh_count if zh_count.get(p, 0) > en_count.get(p, 0)]
            if missing_en:
                issues.append(f"缺失占位符: {', '.join(missing_en)}")
            if missing_zh:
                issues.append(f"多余占位符: {', '.join(missing_zh)}")

        # %msg% 风格
        en_percv = RE_PERCENT_VAR.findall(en)
        zh_percv = RE_PERCENT_VAR.findall(zh)
        if sorted(en_percv) != sorted(zh_percv):
            missing = [p for p in en_percv if p not in zh_percv]
            extra = [p for p in zh_percv if p not in en_percv]
            if missing:
                issues.append(f"缺失变量: {', '.join(missing)}")
            if extra:
                issues.append(f"多余变量: {', '.join(extra)}")

        # {0}, {1} 风格
        en_brace = RE_BRACE_VAR.findall(en)
        zh_brace = RE_BRACE_VAR.findall(zh)
        if sorted(en_brace) != sorted(zh_brace):
            missing_brace = [p for p in en_brace if p not in zh_brace]
            extra_brace = [p for p in zh_brace if p not in en_brace]
            if missing_brace:
                issues.append(f"缺失变量: {{{'}, {'.join(missing_brace)}}}")
            if extra_brace:
                issues.append(f"多余变量: {{{'}, {'.join(extra_brace)}}}")

        if issues:
            return self._verdict(key, en, zh, "❌ FAIL",
                reason="占位符不一致: " + "; ".join(issues),
            )
        return None

    def _check_special_tags(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查特殊标签完整性：§颜色码、&颜色码、$(action)、HTML标签、<br>、\n。"""
        issues: list[str] = []

        # § 格式码
        en_mc = RE_MC_COLOR.findall(en)
        zh_mc = RE_MC_COLOR.findall(zh)
        if sorted(en_mc) != sorted(zh_mc):
            issues.append(f"§颜色码不一致: EN有{len(en_mc)}个, ZH有{len(zh_mc)}个")

        # & 格式码
        en_alt = RE_ALT_COLOR.findall(en)
        zh_alt = RE_ALT_COLOR.findall(zh)
        if sorted(en_alt) != sorted(zh_alt):
            issues.append(f"&颜色码不一致: EN有{len(en_alt)}个, ZH有{len(zh_alt)}个")

        # $(action) / $(l:...)
        en_dollar = RE_PLACEHOLDER_DOLLAR.findall(en)
        zh_dollar = RE_PLACEHOLDER_DOLLAR.findall(zh)
        if sorted(en_dollar) != sorted(zh_dollar):
            issues.append(f"$(action)占位符不一致: EN有{len(en_dollar)}个, ZH有{len(zh_dollar)}个")

        # HTML/XML 标签
        en_html = RE_HTML_TAG.findall(en)
        zh_html = RE_HTML_TAG.findall(zh)
        if sorted(en_html) != sorted(zh_html):
            issues.append(f"HTML标签不一致: EN有{len(en_html)}个, ZH有{len(zh_html)}个")

        # <br> 标签
        en_br = len(RE_BR_TAG.findall(en))
        zh_br = len(RE_BR_TAG.findall(zh))
        if en_br != zh_br:
            issues.append(f"<br>数量不一致: EN={en_br}, ZH={zh_br}")

        # \n 换行
        en_nl = len(RE_NEWLINE.findall(en))
        zh_nl = len(RE_NEWLINE.findall(zh))
        if en_nl != zh_nl:
            issues.append(f"换行符数量不一致: EN={en_nl}, ZH={zh_nl}")

        if issues:
            return self._verdict(key, en, zh, "❌ FAIL",
                reason="格式标签不一致: " + "; ".join(issues),
            )
        return None

    def _check_tellraw_json(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查 tellraw JSON：仅翻译 "text" 键，其余保留原文。"""
        if not is_tellraw_json(en):
            return None
        if not is_tellraw_json(zh):
            return self._verdict(key, en, zh, "❌ FAIL",
                reason="EN为tellraw JSON但ZH格式已破坏",
            )
        try:
            en_obj = json.loads(en)
            zh_obj = json.loads(zh)
        except json.JSONDecodeError:
            return None  # 无法解析，跳过检查

        # 递归比较所有非 text 键
        def compare(obj_en: Any, obj_zh: Any, path: str = "") -> list[str]:
            diffs: list[str] = []
            if isinstance(obj_en, dict) and isinstance(obj_zh, dict):
                for k in obj_en:
                    if k == "text":
                        continue
                    if k not in obj_zh:
                        diffs.append(f"缺少键: {path}.{k}")
                    else:
                        if obj_en[k] != obj_zh[k]:
                            diffs.append(f"非text键被修改: {path}.{k}")
                        diffs.extend(compare(obj_en[k], obj_zh[k], f"{path}.{k}"))
                for k in obj_zh:
                    if k == "text":
                        continue
                    if k not in obj_en:
                        diffs.append(f"多余键: {path}.{k}")
            return diffs

        diffs = compare(en_obj, zh_obj)
        if diffs:
            return self._verdict(key, en, zh, "❌ FAIL",
                reason="tellraw JSON非text键被修改: " + "; ".join(diffs[:3]),
            )
        return None

    def _check_punctuation(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查中文标点规范：全角标点、半角括号[]、中英文间距。"""
        if not is_chinese_text(zh):
            return None

        issues: list[str] = []

        # 半角 → 全角标点 / 括号检查: (正则, 半角符, 全角符, 跳过条件)
        _checks: list[tuple[str, str, str, str | None]] = [
            (r"[\u4e00-\u9fff]\s*\.\s*[\u4e00-\u9fff]", ".", "。", None),
            (r"[\u4e00-\u9fff]\s*,\s*[\u4e00-\u9fff]", ",", "，", None),
            (r"[\u4e00-\u9fff]\s*\?\s*[\u4e00-\u9fff]", "?", "？", None),
            (r"[\u4e00-\u9fff]\s*\!\s*[\u4e00-\u9fff]", "!", "！", None),
            (r"[\u4e00-\u9fff]\s*;\s*[\u4e00-\u9fff]", ";", "；", None),
            (r"[\u4e00-\u9fff]\s*:", ":", "：", "http"),       # 单侧中文即可，排除 URL
            (r"[\u4e00-\u9fff]\s*\(|\)\s*[\u4e00-\u9fff]", "()", "（）", None),
            (r"[【】]", "【】", "[]", None),                     # 全角方括号 → 半角
        ]
        for pattern, half, full, skip_kw in _checks:
            if skip_kw and skip_kw in zh:
                continue
            if re.search(pattern, zh):
                issues.append(f"中文环境中使用了{half}，应使用'{full}'")

        # 中文-中文标点间空格
        punct_space = re.findall(
            r"[\u4e00-\u9fff]\s+[，。；：？！、]|[，。；：？！、]\s+[\u4e00-\u9fff]",
            zh,
        )
        if punct_space:
            issues.append(f"中文与中文标点间有不必要空格（{len(punct_space)}处）")

        # 中英文间空格（Patchouli 手册文本除外，此处标记 SUGGEST）
        if not any(key.startswith(p) for p in cfg.PUNCTUATION_SPACING_WHITELIST):
            en_cn_spaces = re.findall(
                r"[\u4e00-\u9fff]\s+[A-Za-z0-9]|[A-Za-z0-9]\s+[\u4e00-\u9fff]",
                zh,
            )
            if en_cn_spaces:
                issues.append(f"中英文间有不必要空格（{len(en_cn_spaces)}处）")

        if issues:
            return self._verdict(key, en, zh, "⚠️ SUGGEST",
                reason="标点规范: " + "; ".join(issues),
            )
        return None

    def _check_trailing_whitespace(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查尾部空格/标点功能差异。"""
        # 检查中英文尾部空格差异是否可能导致功能问题
        en_trailing = bool(en != en.rstrip())
        zh_trailing = bool(zh != zh.rstrip())
        if en_trailing != zh_trailing and is_chinese_text(zh):
            return self._verdict(key, en, zh, "⚠️ SUGGEST",
                reason=f"尾部空格不一致（EN有={en_trailing}, ZH有={zh_trailing}），可能影响显示",
            )
        return None

    def _check_energy_units(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查能量/体积单位是否被翻译。FE、RF、MB 等应保留原文。"""
        en_units = RE_ENERGY_UNIT.findall(en)
        zh_units = RE_ENERGY_UNIT.findall(zh)
        if en_units and sorted(en_units) != sorted(zh_units):
            missing = [u for u in en_units if u not in zh_units]
            return self._verdict(key, en, zh, "❌ FAIL",
                reason=f"能量/体积单位不应翻译，缺少: {', '.join(missing)}",
            )
        return None

    def _check_ellipsis(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查省略号格式：不应使用三个英文句号 ..."""
        if RE_ELLIPSIS_WRONG.search(zh):
            return self._verdict(key, en, zh, "⚠️ SUGGEST",
                reason="使用了三个英文句号'...'作为省略号，应使用'⋯⋯'（居中省略号）",
            )
        return None

    def _check_sound_subtitle_format(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查声音字幕格式。仅对 subtitles.* 键生效。"""
        if not key.startswith("subtitles.") and not key.startswith("sound."):
            return None

        # ZH 无冒号 + EN 只有1个词（如 "Zapping"）→ 不强求格式
        if "：" not in zh and ":" not in zh:
            en_words = en.split()
            if len(en_words) >= 2 and len(en) < 80:
                return self._verdict(key, en, zh, "⚠️ SUGGEST",
                    reason="声音字幕建议使用'主体：声音'格式（全角冒号）",
                )

    def _check_tree_terms(
        self, key: str, en: str, zh: str
    ) -> dict[str, Any] | None:
        """检查树木相关术语命名一致性。"""
        key_lower = key.lower()
        # 检查 key 是否包含树木相关词
        for term in self.tree_terms:
            if term in key_lower:
                # 树木命名模式检查交给术语表和 LLM
                # 此处仅做基本检查
                return None
        return None

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _verdict(
        key: str, en: str, zh: str, verdict: str, reason: str,
        suggestion: str = "",
    ) -> dict[str, Any]:
        return {
            "key": key,
            "en_current": en,
            "zh_current": zh,
            "verdict": verdict,
            "suggestion": suggestion,
            "reason": reason,
            "source": "format_check",
        }

