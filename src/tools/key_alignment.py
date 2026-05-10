"""
键对齐工具：比较 en_us.json 和 zh_cn.json 的键，输出对齐报告。
用于 translation-reviewer agent 的 Phase 1。

用法:
    python key_alignment.py --en path/to/en_us.json --zh path/to/zh_cn.json [--output path/to/alignment.json]

输出:
    JSON: {
        "matched_entries": [
            {"key": "key1", "en": "English text", "zh": "中文文本"},
            ...
        ],
        "missing_zh": [{"key": "key3", "en": "Only in en"}, ...],
        "extra_zh": [{"key": "key4", "zh": "Only in zh"}, ...],
        "suspicious_untranslated": [
            {"key": "key5", "en": "Same Value", "zh": "Same Value", "reason": "值相同（疑似未翻译）"},
            {"key": "key6", "en": "", "zh": "", "reason": "均为空字符串"},
            ...
        ],
        "stats": {
            "matched": N,
            "missing_zh": N,
            "extra_zh": N,
            "suspicious_untranslated": N,
            "total_en": N,
            "total_zh": N
        }
    }
"""
import json
import re
from pathlib import Path
from src.tools.code_detection import is_likely_code_or_proper_noun
from src.models import AlignmentDict, EntryDict, VerdictDict

_COMMENT_KEY_RE = re.compile(r"^_comment")


def load_json_clean(path: str) -> tuple[dict[str, str], list[str]]:
    """加载 JSON 语言文件，过滤 _comment* 键，检测重复 key。

    返回: (cleaned_data, warnings)
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        raw = f.read()

    warnings: list[str] = []
    seen: dict[str, int] = {}
    stripped = 0

    def _hook(pairs: list[tuple[str, str]]) -> dict[str, str]:
        nonlocal stripped
        result: dict[str, str] = {}
        for key, val in pairs:
            if _COMMENT_KEY_RE.match(key):
                stripped += 1
                continue
            if key in seen:
                warnings.append(f"重复key: {key!r}（第 {seen[key]} 次出现后又出现），JSON只保留最后一次的值")
            else:
                seen[key] = 1
            seen[key] += 1
            result[key] = val
        return result

    data = json.loads(raw, object_pairs_hook=_hook)
    if stripped:
        warnings.insert(0, f"过滤了 {stripped} 个 _comment* 键")
    return data, warnings


def align_keys(en_data: dict[str, str], zh_data: dict[str, str]) -> AlignmentDict:
    en_keys = set(en_data.keys())
    zh_keys = set(zh_data.keys())

    common = en_keys & zh_keys
    matched = [
        {"key": k, "en": en_data[k], "zh": zh_data[k]}
        for k in sorted(common)
    ]
    missing_zh = [
        {"key": k, "en": en_data[k]} for k in sorted(en_keys - zh_keys)
    ]
    extra_zh = [
        {"key": k, "zh": zh_data[k]} for k in sorted(zh_keys - en_keys)
    ]

    suspicious = []
    for entry in matched:
        en_val = entry["en"]
        zh_val = entry["zh"]
        if en_val == zh_val:
            if is_likely_code_or_proper_noun(en_val):
                continue
            if en_val == "":
                reason = "均为空字符串"
            else:
                reason = "值相同（疑似未翻译）"
            suspicious.append({
                "key": entry["key"],
                "en": en_val,
                "zh": zh_val,
                "reason": reason,
            })

    return {
        "matched_entries": matched,
        "missing_zh": missing_zh,
        "extra_zh": extra_zh,
        "suspicious_untranslated": suspicious,
        "stats": {
            "matched": len(matched),
            "missing_zh": len(missing_zh),
            "extra_zh": len(extra_zh),
            "suspicious_untranslated": len(suspicious),
            "total_en": len(en_keys),
            "total_zh": len(zh_keys),
        },
    }



def check_vanilla_collisions(
    en_data: dict[str, str],
    db_path: str = "data/Minecraft.db",
) -> list[VerdictDict]:
    """从 Minecraft.db 读取原版 key 并检测模组覆盖。

    返回碰撞列表，每项: {key, mod_value, vanilla_zh, version_start, version_end, changes}。
    """
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError:
        return []

    try:
        rows = conn.execute(
            "SELECT key, zh_cn, version_start, version_end, changes FROM vanilla_keys"
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    if not rows:
        conn.close()
        return []

    vanilla_map: dict[str, dict] = {}
    for r in rows:
        vanilla_map[r["key"]] = {
            "zh_cn": r["zh_cn"],
            "version_start": r["version_start"],
            "version_end": r["version_end"],
            "changes": r["changes"],
        }
    conn.close()

    mod_keys = set(en_data.keys())
    collisions = mod_keys & set(vanilla_map.keys())

    if not collisions:
        return []

    return [
        {
            "key": k,
            "mod_value": str(en_data[k])[:80],
            "vanilla_zh": vanilla_map[k]["zh_cn"],
            "version_start": vanilla_map[k]["version_start"],
            "version_end": vanilla_map[k]["version_end"],
            "changes": vanilla_map[k]["changes"],
        }
        for k in sorted(collisions)
    ]

