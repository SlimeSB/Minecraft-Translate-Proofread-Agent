"""PR 差异对齐 — 编排器，从 GitHub PR 拉取差异并对齐文件。"""

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.logging import info, warn

from . import _http, _lang, _guideme


def _fetch_pr_data(api_base: str, pr: int, token: str) -> tuple[str, str, list[dict[str, Any]]]:
    """Step 1-2: 获取 PR 详情和变更文件列表。
    返回: (base_sha, head_sha, all_changed_files)
    """
    pr_info = _http.api_get(f"{api_base}/pulls/{pr}", token)
    base_sha = pr_info["base"]["sha"]
    head_sha = pr_info["head"]["sha"]
    info(f"  Base: {base_sha[:12]}")
    info(f"  Head: {head_sha[:12]}")

    page = 1
    all_changed_files: list[dict[str, Any]] = []
    while True:
        url = f"{api_base}/pulls/{pr}/files?per_page=100&page={page}"
        files_page = _http.api_get(url, token)
        if not files_page:
            break
        all_changed_files.extend(files_page)
        if len(files_page) < 100:
            break
        page += 1
        time.sleep(0.1)

    info(f"  变更文件: {len(all_changed_files)} 个")
    return base_sha, head_sha, all_changed_files


def _align_json_mods(
    mods: dict[str, Any],
    raw_base: str,
    raw_head: str,
    token: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Step 3-4: 对齐 JSON 语言文件。
    返回: (all_entries, all_warnings, result_mods)
    """
    all_entries: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    result_mods: dict[str, Any] = {}

    for mod_key, mod_data in mods.items():
        mi = mod_data["mod_info"]
        version, cid, slug = mi["version"], mi["curseforge_id"], mi["slug"]
        resolved_mod_key = f"{version}/{cid}/{slug}"

        en_head = mod_data["en_head"]
        en_base = mod_data["en_base"]
        if en_head or en_base:
            sample = en_head or en_base
            lang_dir = sample.rsplit("/lang/", 1)[0] + "/lang"
        else:
            lang_dir = f"projects/{version}/assets/{cid}/{slug}/lang"

        try:
            old_en_text = _http.raw_get(f"{raw_base}/{lang_dir}/en_us.json", token)
            new_en_text = _http.raw_get(f"{raw_head}/{lang_dir}/en_us.json", token) if en_head is not None else ""
            old_zh_text = _http.raw_get(f"{raw_base}/{lang_dir}/zh_cn.json", token)
            new_zh_text = _http.raw_get(f"{raw_head}/{lang_dir}/zh_cn.json", token) if mod_data["zh_head"] is not None else ""
        except RuntimeError as e:
            warn(f"  警告: 模组 {resolved_mod_key} 拉取失败: {e}")
            continue

        old_en = json.loads(old_en_text) if old_en_text.strip() else {}
        new_en = json.loads(new_en_text) if new_en_text.strip() else {}
        old_zh = json.loads(old_zh_text) if old_zh_text.strip() else {}
        new_zh = json.loads(new_zh_text) if new_zh_text.strip() else {}

        entries, warnings = _lang.align(old_en, new_en, old_zh, new_zh)

        if entries:
            for e in entries:
                e["namespace"] = slug
            result_mods[resolved_mod_key] = {
                "mod_info": mi,
                "entries": entries,
                "full_en": new_en,
                "full_zh": new_zh,
            }
            all_entries.extend(entries)
        all_warnings.extend(warnings)

        time.sleep(0.1)

    return all_entries, all_warnings, result_mods


def _align_guideme_patches(
    all_changed_files: list[dict[str, Any]],
    raw_base: str,
    raw_head: str,
    raw_get_fn,
    token: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Step 4.5: GuideME 文档对齐。
    返回: (guideme_entries, guideme_warnings)
    """
    guideme_entries, guideme_warnings = _guideme.align(
        all_changed_files, raw_base, raw_head, raw_get_fn, token,
    )
    if guideme_entries:
        info(f"  GuideME 文档: {len(guideme_entries)} 条变更")
    return guideme_entries, guideme_warnings


def _filter_deletion_entries(
    all_entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Step 5: 过滤纯删除条目。
    返回: (real_entries, deletions)
    """
    deletions: dict[str, int] = defaultdict(int)
    real_entries: list[dict[str, Any]] = []
    for e in all_entries:
        if e.get("en", "") == "" and e.get("zh", "") == "" and (e.get("old_en") or e.get("old_zh")):
            ns = e.get("namespace", "__unknown__")
            deletions[ns] += 1
        else:
            real_entries.append(e)

    for ns, count in sorted(deletions.items()):
        if count > 5:
            warn(f"  ⚠ [{ns}] 发现 {count} 条删除条目（key已移除），旧版本使用该模组翻译可能出现key缺失，注意兼容性")

    return real_entries, dict(deletions)


def _write_pr_output(
    repo: str,
    pr: int,
    base_sha: str,
    head_sha: str,
    real_entries: list[dict[str, Any]],
    all_warnings: list[dict[str, Any]],
    result_mods: dict[str, Any],
    deletions: dict[str, int],
    guideme_entries: list[dict[str, Any]],
    output_dir: str,
) -> str:
    """Step 6-7: 分组、统计、写入输出文件。
    返回: 合并文件路径
    """
    ns_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in real_entries:
        ns = e.get("namespace", "__unknown__")
        ns_groups[ns].append(e)

    en_changed_count = sum(1 for e in real_entries if "old_en" in e)
    zh_changed_count = sum(1 for e in real_entries if "old_zh" in e)

    result: dict[str, Any] = {
        "repo": repo,
        "pr": pr,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "mods": result_mods,
        "all_entries": real_entries,
        "all_warnings": all_warnings,
        "deletions": deletions,
        "namespaces": {ns: {"count": len(entries), "entries": entries} for ns, entries in ns_groups.items()},
        "stats": {
            "total_changed_keys": len(real_entries),
            "deleted_keys": sum(deletions.values()),
            "en_changed": en_changed_count,
            "zh_changed": zh_changed_count,
            "zh_unchanged_warnings": len(all_warnings),
            "guideme_entries": len(guideme_entries),
            "namespaces": len(ns_groups),
        },
    }

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    combined_path = output_dir_path / "00_pr_alignment.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    ns_dir = output_dir_path / "pr_namespaces"
    ns_dir.mkdir(parents=True, exist_ok=True)  # parents=True is redundant (parent created at line 185) but harmless
    for ns, entries in ns_groups.items():
        ns_file = ns_dir / f"{ns}.json"
        with open(ns_file, "w", encoding="utf-8") as f:
            json.dump({
                "namespace": ns,
                "entries": entries,
                "count": len(entries),
                "warnings": [w for w in all_warnings if any(
                    w.get("key") == e.get("key") for e in entries
                )],
            }, f, ensure_ascii=False, indent=2)

    info(f"[PR Aligner] 完成: {len(real_entries)} 条变更, "
         f"EN 变更 {en_changed_count}, ZH 变更 {zh_changed_count}, "
         f"警告 {len(all_warnings)} 条, {len(ns_groups)} 个 namespace")
    info(f"  合并: {combined_path}")
    if len(ns_groups) > 1:
        info(f"  分文件: {ns_dir} ({', '.join(ns_groups.keys())})")

    return str(combined_path)


def run_pr_aligner(
    repo: str,
    pr: int,
    output_dir: str,
    token: str = "",
) -> str:
    """主入口：执行 PR 对齐流程，返回输出文件路径。"""
    owner, repo_name = repo.split("/", 1)
    api_base = f"https://api.github.com/repos/{owner}/{repo_name}"

    info(f"[PR Aligner] 开始处理 PR #{pr} ({repo})...")

    # Step 1-2: 拉取数据
    base_sha, head_sha, all_changed_files = _fetch_pr_data(api_base, pr, token)

    # Step 3: 分组 + 准备原始 URL
    mods = _lang.group_mod_files(all_changed_files)
    info(f"  模组语言文件: {len(mods)} 组")

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{base_sha}"
    raw_head = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{head_sha}"

    # Step 4: 对齐 JSON
    all_entries, all_warnings, result_mods = _align_json_mods(mods, raw_base, raw_head, token)

    # Step 4.5: GuideME 对齐
    guideme_entries, guideme_warnings = _align_guideme_patches(
        all_changed_files, raw_base, raw_head, _http.raw_get, token,
    )
    if guideme_entries:
        all_entries.extend(guideme_entries)
        all_warnings.extend(guideme_warnings)
        result_mods["__guideme__"] = {
            "mod_info": {"version": "", "curseforge_id": "", "slug": ""},
            "entries": guideme_entries,
        }

    # Step 5: 过滤纯删除
    real_entries, deletions = _filter_deletion_entries(all_entries)

    # Step 6-7: 输出
    return _write_pr_output(
        repo, pr, base_sha, head_sha,
        real_entries, all_warnings, result_mods, deletions,
        guideme_entries, output_dir,
    )
