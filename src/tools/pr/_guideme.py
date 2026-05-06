"""PR 审校 — GuideME 文档对齐。"""
import re
from typing import Any

_GUIDEME_PATH_RE = re.compile(
    r"^projects/([^/]+)/assets/([^/]+)/([^/]+)/ae2guide/(_zh_cn/)?(.+\.md)$"
)


def match(path: str) -> dict[str, str] | None:
    """尝试匹配 GuideME 路径，返回解析信息或 None。"""
    m = _GUIDEME_PATH_RE.match(path)
    if not m:
        return None
    return {
        "version": m.group(1),
        "curseforge_id": m.group(2),
        "slug": m.group(3),
        "is_zh": bool(m.group(4)),
        "rel_path": m.group(5),
    }


def align(
    changed_files: list[dict[str, Any]],
    raw_base: str,
    raw_head: str,
    raw_get_fn,
    token: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对齐 GuideME .md 文档文件（按相对路径匹配中英文）。

    raw_get_fn: (url, token) -> str  用于拉取文件内容。
    """
    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    groups: dict[str, dict[str, dict[str, str | None]]] = {}
    for f in changed_files:
        filename = f.get("filename", "")
        info = match(filename)
        if not info:
            continue

        mod_key = f"{info['version']}/{info['curseforge_id']}/{info['slug']}"
        rel_path = info["rel_path"]

        if mod_key not in groups:
            groups[mod_key] = {}
        if rel_path not in groups[mod_key]:
            groups[mod_key][rel_path] = {"en_base": None, "en_head": None, "zh_base": None, "zh_head": None}

        status = f.get("status", "modified")
        slot = "zh" if info["is_zh"] else "en"
        head_key = f"{slot}_head"
        base_key = f"{slot}_base"

        if status != "removed":
            groups[mod_key][rel_path][head_key] = filename
        if status not in ("added", "renamed", "copied") and "removed" not in status:
            groups[mod_key][rel_path][base_key] = filename

    for mod_key, pages in groups.items():
        version, curseforge_id, slug = mod_key.split("/", 2)
        base_path = f"projects/{version}/assets/{curseforge_id}/{slug}/ae2guide"

        for rel_path, paths in pages.items():
            en_url = f"{base_path}/{rel_path}"
            zh_url = f"{base_path}/_zh_cn/{rel_path}"

            try:
                old_en = raw_get_fn(f"{raw_base}/{en_url}", token) if paths["en_base"] else ""
                new_en = raw_get_fn(f"{raw_head}/{en_url}", token) if paths["en_head"] else ""
                old_zh = raw_get_fn(f"{raw_base}/{zh_url}", token) if paths["zh_base"] else ""
                new_zh = raw_get_fn(f"{raw_head}/{zh_url}", token) if paths["zh_head"] else ""
            except RuntimeError as e:
                warnings.append({"key": rel_path, "type": "fetch_error", "message": str(e)})
                continue

            en_changed = (old_en != new_en)
            zh_changed = (old_zh != new_zh)

            if not en_changed and not zh_changed:
                continue

            entry: dict[str, Any] = {
                "key": f"ae2guide:{rel_path}",
                "en": new_en,
                "zh": new_zh,
            }
            if en_changed:
                entry["old_en"] = old_en
                if not zh_changed and old_en.strip():
                    warnings.append({
                        "key": entry["key"],
                        "type": "en_changed_zh_unchanged",
                        "message": f"GuideME原文变更但翻译未跟随: {rel_path}",
                    })
            if zh_changed:
                entry["old_zh"] = old_zh

            review_type = "normal"
            if en_changed and not zh_changed:
                review_type = "en_changed_zh_unchanged"
            elif zh_changed and not en_changed:
                review_type = "zh_only_change"
            entry["review_type"] = review_type
            entries.append(entry)

    return entries, warnings
