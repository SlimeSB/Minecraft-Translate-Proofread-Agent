"""Phase 1: 键对齐（传统模式）或 PR 数据加载。"""
import json

from src.logging import info
from src.models import (
    AlignmentDict,
    EntryDict,
    PipelineContext,
    PRAlignmentEntryDict,
    PRChangeMetaDict,
    PRWarningDict,
)
from src.storage.database import PipelineDB
from src.tools.key_alignment import align_keys, load_json_clean, merge_indexed_entries


def run_phase1(ctx: PipelineContext) -> None:
    if ctx.pr_mode:
        _load_pr_alignment(ctx)
    else:
        _align_keys(ctx)


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
            "_change": {
                "old_en": entry.get("old_en", ""),
                "old_zh": entry.get("old_zh", ""),
            },
        })

    ctx.en_data = {e["key"]: e["en"] for e in matched}
    ctx.zh_data = {e["key"]: e["zh"] for e in matched}
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

    with PipelineDB(ctx.output_dir / "pipeline.db") as db:
        db.save_alignment(ctx.alignment)

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

    mods = data.get("mods", {})
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
    with PipelineDB(ctx.output_dir / "pipeline.db") as db:
        db.save_alignment(ctx.alignment)
