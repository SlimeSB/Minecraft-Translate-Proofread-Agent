"""PR 差异对齐 — 编排器，从 GitHub PR 拉取差异并对齐文件。"""

import json
import time
from pathlib import Path
from typing import Any

from . import _http, _lang, _guideme


def run_pr_aligner(
    repo: str,
    pr: int,
    output_dir: str,
    token: str = "",
) -> str:
    """主入口：执行 PR 对齐流程，返回输出文件路径。"""
    owner, repo_name = repo.split("/", 1)
    api_base = f"https://api.github.com/repos/{owner}/{repo_name}"

    print(f"[PR Aligner] 开始处理 PR #{pr} ({repo})...")

    # Step 1: 获取 PR 详情
    pr_info = _http.api_get(f"{api_base}/pulls/{pr}", token)
    base_sha = pr_info["base"]["sha"]
    head_sha = pr_info["head"]["sha"]
    print(f"  Base: {base_sha[:12]}")
    print(f"  Head: {head_sha[:12]}")

    # Step 2: 获取变更文件列表
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

    print(f"  变更文件: {len(all_changed_files)} 个")

    # Step 3: 按模组分组建 JSON 语言文件
    mods = _lang.group_mod_files(all_changed_files)
    print(f"  模组语言文件: {len(mods)} 组")

    # Step 4: 对齐 JSON lang
    all_entries: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    result_mods: dict[str, Any] = {}

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{base_sha}"
    raw_head = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{head_sha}"

    for mod_key, mod_data in mods.items():
        mi = mod_data["mod_info"]
        version, cid, slug = mi["version"], mi["curseforge_id"], mi["slug"]
        resolved_mod_key = f"{version}/{cid}/{slug}"
        base_path = f"projects/{version}/assets/{cid}/{slug}/lang"

        try:
            old_en_text = _http.raw_get(f"{raw_base}/{base_path}/en_us.json", token)
            new_en_text = _http.raw_get(f"{raw_head}/{base_path}/en_us.json", token) if mod_data["en_head"] is not None else ""
            old_zh_text = _http.raw_get(f"{raw_base}/{base_path}/zh_cn.json", token)
            new_zh_text = _http.raw_get(f"{raw_head}/{base_path}/zh_cn.json", token) if mod_data["zh_head"] is not None else ""
        except RuntimeError as e:
            print(f"  警告: 模组 {resolved_mod_key} 拉取失败: {e}")
            continue

        old_en = json.loads(old_en_text) if old_en_text.strip() else {}
        new_en = json.loads(new_en_text) if new_en_text.strip() else {}
        old_zh = json.loads(old_zh_text) if old_zh_text.strip() else {}
        new_zh = json.loads(new_zh_text) if new_zh_text.strip() else {}

        entries, warnings = _lang.align(old_en, new_en, old_zh, new_zh)

        if entries:
            result_mods[resolved_mod_key] = {
                "mod_info": mi,
                "entries": entries,
            }
            all_entries.extend(entries)
        all_warnings.extend(warnings)

        time.sleep(0.1)

    # Step 4.5: GuideME 文档对齐
    guideme_entries, guideme_warnings = _guideme.align(
        all_changed_files, raw_base, raw_head, _http.raw_get, token,
    )
    if guideme_entries:
        print(f"  GuideME 文档: {len(guideme_entries)} 条变更")
        all_entries.extend(guideme_entries)
        all_warnings.extend(guideme_warnings)
        result_mods["__guideme__"] = {
            "mod_info": {"version": "", "curseforge_id": "", "slug": ""},
            "entries": guideme_entries,
        }

    # Step 5: 统计
    en_changed_count = sum(1 for e in all_entries if "old_en" in e)
    zh_changed_count = sum(1 for e in all_entries if "old_zh" in e)
    en_unchanged_zh_changed = sum(1 for e in all_entries if e.get("review_type") == "zh_only_change")

    result: dict[str, Any] = {
        "repo": repo,
        "pr": pr,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "mods": result_mods,
        "all_entries": all_entries,
        "all_warnings": all_warnings,
        "stats": {
            "total_changed_keys": len(all_entries),
            "en_changed": en_changed_count,
            "zh_changed": zh_changed_count,
            "en_unchanged_zh_changed": en_unchanged_zh_changed,
            "zh_unchanged_warnings": len(all_warnings),
            "guideme_entries": len(guideme_entries),
        },
    }

    # 保存
    output_path = Path(output_dir) / "00_pr_alignment.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[PR Aligner] 完成: {len(all_entries)} 条变更, "
          f"EN 变更 {en_changed_count}, ZH 变更 {zh_changed_count}, "
          f"警告 {len(all_warnings)} 条")
    print(f"  输出: {output_path}")

    return str(output_path)
