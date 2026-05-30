"""Phase 1: 键对齐（传统模式）或 PR 数据加载。"""

from src.logging import info, warn
from src.models import (
    AlignmentDict,
    EntryDict,
    PipelineContext,
    PRAlignmentEntryDict,
    PRChangeMetaDict,
    PRWarningDict,
    PRVersionGroups,
    VersionGroupData,
)
from src.tools.key_alignment import align_keys, load_json_clean, merge_indexed_entries
from src.tools.version_cmp import sort_versions_desc
from src.tools.pr.cross_version_diff import CrossVersionDiff, compute_all_cross_version_diffs


def run_phase1(ctx: PipelineContext) -> None:
    if ctx.pr_mode:
        _load_pr_alignment(ctx)
    else:
        _align_keys(ctx)


def _regroup_mods_by_slug(mods: dict) -> dict[str, PRVersionGroups]:
    """按 slug 重组 mods 为 version_groups。"""
    groups: dict[str, PRVersionGroups] = {}
    for mod_key, mod_data in mods.items():
        mi = mod_data.get("mod_info", {})
        slug = mi.get("slug", "")
        version = mi.get("version", "")
        if not slug or not version:
            continue
        if slug not in groups:
            groups[slug] = {
                "slug": slug,
                "versions": [],
                "version_data": {},
                "cross_version_diffs": {},
            }
        groups[slug]["version_data"][version] = {
            "version": version,
            "full_en": mod_data.get("full_en", {}),
            "full_zh": mod_data.get("full_zh", {}),
            "entries": mod_data.get("entries", []),
        }
    for slug, g in groups.items():
        g["versions"] = sort_versions_desc(list(g["version_data"].keys()))
    return groups


def _build_combined_full_data(
    version_groups: dict[str, PRVersionGroups],
) -> tuple[dict[str, str], dict[str, str]]:
    """从所有版本的全量数据合并，使用复合 key "{slug}/{ver}/{k}" 避免碰撞。"""
    combined_en: dict[str, str] = {}
    combined_zh: dict[str, str] = {}
    for slug, g in version_groups.items():
        for ver, vd in g["version_data"].items():
            for k, v in vd["full_en"].items():
                composite = f"{slug}/{ver}/{k}"
                combined_en[composite] = v
            for k, v in vd["full_zh"].items():
                composite = f"{slug}/{ver}/{k}"
                combined_zh[composite] = v
    return combined_en, combined_zh


def _build_pr_en_zh_data(
    ctx: PipelineContext,
    matched: list[EntryDict],
    version_groups: dict[str, PRVersionGroups],
) -> tuple[dict[str, str], dict[str, str]]:
    """构建 en_data/zh_data 并为 matched_entries 注入 cross-version ref_*。"""
    # 计算所有跨版本差异
    for slug, g in version_groups.items():
        full_data: dict[str, tuple[dict[str, str], dict[str, str]]] = {}
        for ver in g["versions"]:
            vs = g["version_data"].get(ver)
            if vs:
                full_data[ver] = (vs["full_en"], vs["full_zh"])
        g["cross_version_diffs"] = compute_all_cross_version_diffs(
            slug, g["versions"], full_data,
        )
    ctx.pr_version_groups = version_groups

    # 为 diff entry 注入 ref_* 参考值
    missing_ver_count = 0
    for entry in matched:
        slug = entry.get("slug", "")
        ver = entry.get("version", "")
        g = version_groups.get(slug)
        if not g:
            continue
        diff = g["cross_version_diffs"].get(ver)
        if not diff:
            continue
        k = entry["key"]
        ref_info = diff.key_refs.get(k)
        if ref_info:
            chg = entry.get("_change") or {}
            chg["ref_version"] = ref_info["ref_version"]
            chg["ref_en"] = ref_info.get("ref_en", "")
            chg["ref_zh"] = ref_info.get("ref_zh", "")
            entry["_change"] = chg
        elif k in diff.modified_keys:
            missing_ver_count += 1

    en_data: dict[str, str] = {}
    zh_data: dict[str, str] = {}
    for e in matched:
        en_data[e["key"]] = e.get("en", "")
        zh_data[e["key"]] = e.get("zh", "")
    return en_data, zh_data


def _load_pr_alignment(ctx: PipelineContext) -> None:
    info("[PR Mode] 加载 PR 对齐数据...")
    data = ctx.pr_alignment
    matched: list[EntryDict] = []
    for entry in data.get("all_entries", []):
        key = entry["key"]
        matched.append({
            "key": key,
            "en": entry["en"],
            "zh": entry["zh"],
            "namespace": entry.get("namespace", ""),
            "format": entry.get("format", "json"),
            "version": entry.get("version", ""),
            "file_path": entry.get("file_path", ""),
            "slug": entry.get("slug", ""),
            "_change": {
                "old_en": entry.get("old_en", ""),
                "old_zh": entry.get("old_zh", ""),
            },
        })

    # 按 slug 重组多版本数据
    mods = data.get("mods", {})
    version_groups = _regroup_mods_by_slug(mods)
    if version_groups:
        info(f"  版本组: {len(version_groups)} 个 slug")
        for slug, g in version_groups.items():
            entries_count = sum(
                len(vd.get("entries", [])) for vd in g["version_data"].values()
            )
            info(f"    {slug}: {', '.join(g['versions'])} ({entries_count} 条变更)")

    # 构建全版本合并数据（供 Phase 2 术语提取）
    combined_en, combined_zh = _build_combined_full_data(version_groups)
    ctx.pr_combined_full_en = combined_en
    ctx.pr_combined_full_zh = combined_zh
    if combined_en:
        info(f"  全量合并数据: {len(combined_en)} 个复合 key")

    # 构建 en/zh data 并注入跨版本 ref
    en_data, zh_data = _build_pr_en_zh_data(ctx, matched, version_groups)
    ctx.en_data = en_data
    ctx.zh_data = zh_data

    ctx.alignment = {
        "matched_entries": matched,
        "missing_zh": [], "extra_zh": [], "suspicious_untranslated": [],
        "stats": {
            "matched": len(matched), "missing_zh": 0, "extra_zh": 0,
            "suspicious_untranslated": 0, "total_en": len(matched), "total_zh": len(matched),
        },
    }
    ctx.alignment = merge_indexed_entries(ctx.alignment)
    matched = ctx.alignment["matched_entries"]

    # Phase 1: INSERT OR REPLACE INTO entries (state=0, verdict=0, diagnoses='[]')
    db = ctx.db
    for e in matched:
        chg = e.get("_change") or {}
        db.execute(
            "INSERT OR REPLACE INTO entries "
            "(key, en, zh, format, namespace, version, file_path, slug, old_en, old_zh, state, verdict, diagnoses) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,0,0,'[]')",
            (e["key"], e.get("en", ""), e.get("zh", ""),
             e.get("format", ""), e.get("namespace", ""),
             e.get("version", ""), e.get("file_path", ""),
             e.get("slug", ""),
             chg.get("old_en", ""), chg.get("old_zh", "")))
    db.commit()

    for entry in data.get("all_entries", []):
        key = entry["key"]
        ctx.pr_change_meta[key] = {
            "en_changed": "old_en" in entry,
            "zh_changed": "old_zh" in entry,
            "old_en": entry.get("old_en", ""),
            "old_zh": entry.get("old_zh", ""),
            "warning": entry.get("review_type") == "en_changed_zh_unchanged",
            "review_type": entry.get("review_type", "normal"),
            "version": entry.get("version", ""),
        }
        if entry.get("review_type") == "zh_only_change":
            ctx.zh_only_entries.append(entry)

    ctx.pr_warnings = data.get("all_warnings", [])

    if not version_groups:
        # 兼容旧格式（无 slug 字段）
        for mod_data in mods.values():
            full_en = mod_data.get("full_en", {})
            full_zh = mod_data.get("full_zh", {})
            ctx.pr_full_en_data.update(full_en)
            ctx.pr_full_zh_data.update(full_zh)
        if ctx.pr_full_en_data:
            info(f"  全量数据: {len(ctx.pr_full_en_data)} 个唯一 key")

    info(f"  已加载: {len(matched)} 条变更, {len(ctx.pr_warnings)} 条警告, "
          f"{len(ctx.zh_only_entries)} 条 ZH-only 变更")


def _align_keys(ctx: PipelineContext) -> None:
    info("[Phase 1] 键对齐...")
    warnings: list[str] = []
    is_lang = str(ctx.en_path).endswith(".lang")
    if is_lang:
        from src.tools.lang_parser import load_lang
        ctx.en_data, en_w = load_lang(str(ctx.en_path))
        ctx.zh_data, zh_w = load_lang(str(ctx.zh_path))
        warnings.extend(f"[EN] {w}" for w in en_w)
        warnings.extend(f"[ZH] {w}" for w in zh_w)
    else:
        ctx.en_data, en_w = load_json_clean(str(ctx.en_path))
        ctx.zh_data, zh_w = load_json_clean(str(ctx.zh_path))
        warnings.extend(f"[EN] {w}" for w in en_w)
        warnings.extend(f"[ZH] {w}" for w in zh_w)
    for w in warnings:
        info(f"  {w}")

    ctx.alignment = align_keys(ctx.en_data, ctx.zh_data)
    fmt = "lang" if is_lang else "json"
    for e in ctx.alignment.get("matched_entries", []):
        e["format"] = fmt
    ctx.alignment = merge_indexed_entries(ctx.alignment)

    stats = ctx.alignment["stats"]
    info(f"  ✅ 已对齐: {stats['matched']} | ❌ 未翻译: {stats['missing_zh']} | "
          f"⚠️ 多余键: {stats['extra_zh']} | 🔶 疑似未翻译: {stats['suspicious_untranslated']}")

    # Phase 1: INSERT OR REPLACE INTO entries (state=0, verdict=0, diagnoses='[]')
    db = ctx.db
    for e in ctx.alignment.get("matched_entries", []):
        chg = e.get("_change") or {}
        db.execute(
            "INSERT OR REPLACE INTO entries "
            "(key, en, zh, format, namespace, version, file_path, slug, old_en, old_zh, state, verdict, diagnoses) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,0,0,'[]')",
            (e["key"], e.get("en", ""), e.get("zh", ""),
             e.get("format", ""), e.get("namespace", ""),
             e.get("version", ""), e.get("file_path", ""),
             e.get("slug", ""),
             chg.get("old_en", ""), chg.get("old_zh", "")))
    db.commit()
