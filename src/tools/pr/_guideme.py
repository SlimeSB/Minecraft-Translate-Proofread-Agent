"""PR 审校 — GuideME 文档对齐。"""
import re
from typing import Any

_GUIDEME_PATH_RE = re.compile(
    r"^projects/(?:assets/(?P<cid>[^/]+)/(?P<ver>[^/]+)"
    r"|(?P<ver2>[^/]+)/assets/(?P<cid2>[^/]+))"
    r"/(?P<slug>[^/]+)/ae2guide/(?P<zh_prefix>_zh_cn/)?"
    r"(?P<rel_path>.+\.md)$"
)


def match(path: str) -> dict[str, str] | None:
    """尝试匹配 GuideME 路径（兼容新旧两种目录结构）。"""
    m = _GUIDEME_PATH_RE.match(path)
    if not m:
        return None
    return {
        "curseforge_id": m.group("cid") or m.group("cid2"),
        "version": m.group("ver") or m.group("ver2"),
        "slug": m.group("slug"),
        "is_zh": bool(m.group("zh_prefix")),
        "rel_path": m.group("rel_path"),
    }


def align(
    changed_files: list[dict[str, Any]],
    raw_base: str,
    raw_head: str,
    raw_get_fn,
    token: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对齐 GuideME .md 文档文件（按相对路径匹配中英文）。"""
    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    # 按 rel_path 分组：{rel_path: {en_base, en_head, zh_base, zh_head}}
    groups: dict[str, dict[str, str | None]] = {}
    for f in changed_files:
        filename = f.get("filename", "")
        info = match(filename)
        if not info:
            continue

        rel_path = info["rel_path"]
        if rel_path not in groups:
            groups[rel_path] = {"paths": {"en_base": None, "en_head": None, "zh_base": None, "zh_head": None}, "namespace": info["slug"]}
        g = groups[rel_path]

        status = f.get("status", "modified")
        slot_base = "zh_base" if info["is_zh"] else "en_base"
        slot_head = "zh_head" if info["is_zh"] else "en_head"

        if status != "removed":
            g["paths"][slot_head] = filename
        if status not in ("added", "renamed", "copied") and "removed" not in status:
            g["paths"][slot_base] = filename

    # 对每个页面，如果只有 en 没有 zh，从 en 路径推导 zh 路径
    for rel_path, g in groups.items():
        paths = g["paths"]
        if paths["zh_head"] is None and paths["en_head"]:
            paths["zh_head"] = paths["en_head"].replace("/ae2guide/", "/ae2guide/_zh_cn/")
        if paths["zh_base"] is None and paths["en_base"]:
            paths["zh_base"] = paths["en_base"].replace("/ae2guide/", "/ae2guide/_zh_cn/")

    # 拉取文件内容并对齐
    for rel_path, g in groups.items():
        paths = g["paths"]
        try:
            old_en = raw_get_fn(f"{raw_base}/{paths['en_base']}", token) if paths["en_base"] else ""
            new_en = raw_get_fn(f"{raw_head}/{paths['en_head']}", token) if paths["en_head"] else ""
            old_zh = raw_get_fn(f"{raw_base}/{paths['zh_base']}", token) if paths["zh_base"] else ""
            new_zh = raw_get_fn(f"{raw_head}/{paths['zh_head']}", token) if paths["zh_head"] else ""
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
            "namespace": g["namespace"],
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

        if en_changed and not zh_changed:
            entry["review_type"] = "en_changed_zh_unchanged"
        elif zh_changed and not en_changed:
            entry["review_type"] = "zh_only_change"
        else:
            entry["review_type"] = "normal"
        entries.append(entry)

    return entries, warnings
