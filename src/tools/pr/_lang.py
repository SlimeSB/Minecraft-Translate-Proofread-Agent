"""PR 审校 — JSON 语言文件对齐。"""
import json
import re
from typing import Any

_LANG_PATH_RE = re.compile(
    r"^projects/(?:assets/(?P<cid>[^/]+)/(?P<ver>[^/]+)"
    r"|(?P<ver2>[^/]+)/assets/(?P<cid2>[^/]+))"
    r"/(?P<slug>[^/]+)/lang/(?P<lang>en_us|zh_cn)\.json$"
)


def match(path: str) -> dict[str, str] | None:
    """尝试匹配语言文件路径（兼容新旧两种目录结构）。"""
    m = _LANG_PATH_RE.match(path)
    if not m:
        return None
    return {
        "curseforge_id": m.group("cid") or m.group("cid2"),
        "version": m.group("ver") or m.group("ver2"),
        "slug": m.group("slug"),
        "lang": m.group("lang"),
    }


def group_mod_files(
    changed_files: list[dict[str, Any]],
) -> dict[str, dict[str, str | None]]:
    """将变更文件按模组分组。

    返回: {mod_key: {en_base, en_head, zh_base, zh_head, mod_info}}
    """
    mods: dict[str, dict[str, str | None]] = {}

    for f in changed_files:
        filename = f.get("filename", "")
        parsed = match(filename)
        if not parsed:
            continue

        mod_key = f"{parsed['version']}/{parsed['curseforge_id']}/{parsed['slug']}"
        if mod_key not in mods:
            mods[mod_key] = {
                "mod_info": {
                    "version": parsed["version"],
                    "curseforge_id": parsed["curseforge_id"],
                    "slug": parsed["slug"],
                },
                "en_base": None,
                "en_head": None,
                "zh_base": None,
                "zh_head": None,
            }

        status = f.get("status", "modified")
        if parsed["lang"] == "en_us":
            if status == "removed":
                mods[mod_key]["en_base"] = filename
            else:
                mods[mod_key]["en_head"] = filename
                if "renamed" not in status and "added" not in status and "copied" not in status:
                    mods[mod_key]["en_base"] = filename
        elif parsed["lang"] == "zh_cn":
            if status != "removed":
                mods[mod_key]["zh_head"] = filename

    for mod_key, mod_data in mods.items():
        if mod_data["zh_head"] is None:
            en_path = mod_data["en_head"]
            if en_path:
                zh_path = en_path.replace("/en_us.json", "/zh_cn.json")
                mod_data["zh_head"] = zh_path
                mod_data["zh_base"] = zh_path

    return mods


def _load_json(text: str) -> dict[str, str]:
    if not text.strip():
        return {}
    return json.loads(text)


def align(
    old_en: dict[str, str],
    new_en: dict[str, str],
    old_zh: dict[str, str],
    new_zh: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对齐单个模组的四份 JSON 文件。

    返回: (entries, warnings)
    """
    all_keys = sorted(set(old_en.keys()) | set(new_en.keys()) |
                      set(old_zh.keys()) | set(new_zh.keys()))

    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for key in all_keys:
        o_en = old_en.get(key, "")
        n_en = new_en.get(key, "")
        o_zh = old_zh.get(key, "")
        n_zh = new_zh.get(key, "")

        en_changed = (o_en != n_en)
        zh_changed = (o_zh != n_zh)

        if not en_changed and not zh_changed:
            continue

        entry: dict[str, Any] = {"key": key, "en": n_en, "zh": n_zh, "format": "json"}

        if en_changed and zh_changed:
            review_type = "normal"
        elif en_changed:
            review_type = "en_changed_zh_unchanged"
        else:
            review_type = "zh_only_change"

        if en_changed:
            entry["old_en"] = o_en
            if not zh_changed and o_en:
                warnings.append({
                    "key": key,
                    "type": "en_changed_zh_unchanged",
                    "message": "原文变更（EN）但翻译（ZH）未跟随变更",
                })

        if zh_changed:
            entry["old_zh"] = o_zh

        entry["review_type"] = review_type
        entries.append(entry)

    return entries, warnings
