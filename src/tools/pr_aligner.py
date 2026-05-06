"""
PR 差异对齐器：从 GitHub PR 拉取差异，对齐文件并输出 key/en/zh（含可选 old_en/old_zh）。

用法:
    python -m src.tools.pr_aligner --repo CFPAOrg/Minecraft-Mod-Language-Package --pr 1234 -o ./output/
    python -m src.tools.pr_aligner --repo CFPAOrg/Minecraft-Mod-Language-Package --pr 1234 -o ./output/ --token ghp_xxx

输出:
    output/00_pr_alignment.json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# 语言文件路径正则：projects/{version}/assets/{curseforge_id}/{slug}/lang/{lang}.json
_LANG_PATH_RE = re.compile(
    r"^projects/([^/]+)/assets/([^/]+)/([^/]+)/lang/(en_us|zh_cn)\.json$"
)

_USER_AGENT = "Mozilla/5.0 (compatible; MinecraftTranslateProofreadAgent/1.0)"


def _build_headers(token: str = "") -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_get(url: str, token: str = "") -> Any:
    """调用 GitHub API 并返回解析后的 JSON。"""
    req = urllib.request.Request(url, headers=_build_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API 错误 {e.code}: {body}") from e


def _raw_get(url: str, token: str = "", retries: int = 3) -> str:
    """拉取 raw.githubusercontent.com 的文件内容（带重试）。"""
    headers = _build_headers(token)
    if token:
        url += f"?token={token}"
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            timeout = 30 * attempt
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""  # 文件不存在
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Raw 文件错误 {e.code}: {body}") from e
        except (TimeoutError, urllib.error.URLError) as e:
            last_err = e
            if attempt < retries:
                wait = attempt * 2
                print(f"  [重试 {attempt}/{retries}] {url.split('/')[-1]} 超时，{wait}s 后重试...")
                time.sleep(wait)
    raise RuntimeError(f"Raw 文件拉取失败（重试{retries}次）: {last_err}")


def _parse_lang_path(path: str) -> dict[str, str] | None:
    """解析语言文件路径，返回 version, curseforge_id, slug, lang 的字典。"""
    m = _LANG_PATH_RE.match(path)
    if not m:
        return None
    return {
        "version": m.group(1),
        "slug": m.group(3),
        "curseforge_id": m.group(2),
        "lang": m.group(4),
    }


def _group_mod_files(
    changed_files: list[dict[str, Any]],
) -> dict[str, dict[str, str | None]]:
    """将变更文件按模组分组。

    返回: {mod_key: {en_base: path|None, en_head: path|None, zh_base: path|None, zh_head: path|None}}
    """
    mods: dict[str, dict[str, str | None]] = {}

    for f in changed_files:
        filename = f.get("filename", "")
        parsed = _parse_lang_path(filename)
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
            if "renamed" in status or "added" in status or "copied" in status:
                # 对于新增/重命名，base 可能不存在
                if mods[mod_key]["en_base"] is None:
                    mods[mod_key]["en_base"] = None  # 标记为 None
                # 但 head 一定存在
            mods[mod_key]["en_head"] = filename
            mods[mod_key]["en_base"] = filename  # base 用同一路径，实际从 base sha 拉
        elif parsed["lang"] == "zh_cn":
            mods[mod_key]["zh_head"] = filename

    # 如果只有 en 变更没有 zh 变更，zh_base 和 zh_head 用 en 同路径
    for mod_key, mod_data in mods.items():
        if mod_data["zh_head"] is None:
            # zh 没有变更，用 en 路径
            en_path = mod_data["en_head"]
            if en_path:
                zh_path = en_path.replace("/en_us.json", "/zh_cn.json")
                mod_data["zh_head"] = zh_path
                mod_data["zh_base"] = zh_path

    return mods


def _load_json(text: str) -> dict[str, str]:
    """加载 JSON 字符串，返回扁平键值字典。"""
    if not text.strip():
        return {}
    return json.loads(text)


def _align_mod_entries(
    old_en: dict[str, str],
    new_en: dict[str, str],
    old_zh: dict[str, str],
    new_zh: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对齐单个模组的四份文件。

    返回: (entries, warnings)
    输出字段: key, en, zh 始终存在;
              old_en 仅当 EN 有变更时存在;
              old_zh 仅当 ZH 有变更时存在。
    """
    all_keys = sorted(set(old_en.keys()) | set(new_en.keys()) | set(old_zh.keys()) | set(new_zh.keys()))

    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for key in all_keys:
        o_en = old_en.get(key, "")
        n_en = new_en.get(key, "")
        o_zh = old_zh.get(key, "")
        n_zh = new_zh.get(key, "")

        en_changed = (o_en != n_en)
        zh_changed = (o_zh != n_zh)

        # 如果 EN 和 ZH 都没变，跳过
        if not en_changed and not zh_changed:
            continue

        entry: dict[str, Any] = {
            "key": key,
            "en": n_en,
            "zh": n_zh,
        }

        if en_changed and zh_changed:
            review_type = "normal"
        elif en_changed:
            review_type = "en_changed_zh_unchanged"
        else:
            review_type = "zh_only_change"

        if en_changed:
            entry["old_en"] = o_en
            if not zh_changed and o_en:
                # 原文有实际内容但翻译未跟随变更 → warning
                # 排除旧原文为空的情况（即新增条目，不算变更）
                warnings.append({
                    "key": key,
                    "type": "en_changed_zh_unchanged",
                    "message": f"原文变更（EN）但翻译（ZH）未跟随变更",
                })

        if zh_changed:
            entry["old_zh"] = o_zh

        entry["review_type"] = review_type
        entries.append(entry)

    return entries, warnings


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
    pr_info = _api_get(f"{api_base}/pulls/{pr}", token)
    base_sha = pr_info["base"]["sha"]
    head_sha = pr_info["head"]["sha"]
    print(f"  Base: {base_sha[:12]}")
    print(f"  Head: {head_sha[:12]}")

    # Step 2: 获取变更文件列表
    page = 1
    all_changed_files: list[dict[str, Any]] = []
    while True:
        url = f"{api_base}/pulls/{pr}/files?per_page=100&page={page}"
        files_page = _api_get(url, token)
        if not files_page:
            break
        all_changed_files.extend(files_page)
        if len(files_page) < 100:
            break
        page += 1
        time.sleep(0.1)

    print(f"  变更文件: {len(all_changed_files)} 个")

    # Step 3: 按模组分组建语言文件
    mods = _group_mod_files(all_changed_files)
    print(f"  模组语言文件: {len(mods)} 组")

    # Step 4: 对每个模组，拉取 4 文件并对比
    all_entries: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{base_sha}"
    raw_head = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{head_sha}"

    for mod_key, mod_data in mods.items():
        mi = mod_data["mod_info"]
        version = mi["version"]
        cid = mi["curseforge_id"]
        slug = mi["slug"]
        base_path = f"projects/{version}/assets/{cid}/{slug}/lang"
        en_path = f"{base_path}/en_us.json"
        zh_path = f"{base_path}/zh_cn.json"

        # 拉取 old_en
        old_en_url = f"{raw_base}/{en_path}"
        old_en_text = _raw_get(old_en_url, token)

        # 拉取 new_en
        new_en_url = f"{raw_head}/{en_path}"
        new_en_text = _raw_get(new_en_url, token)

        # 拉取 old_zh
        old_zh_text = _raw_get(f"{raw_base}/{zh_path}", token)

        # 拉取 new_zh
        new_zh_text = _raw_get(f"{raw_head}/{zh_path}", token)

        resolved_mod_key = f"{version}/{cid}/{slug}"

        entries, warnings = _align_mod_entries(
            _load_json(old_en_text), _load_json(new_en_text),
            _load_json(old_zh_text), _load_json(new_zh_text),
        )

        # 添加 mod 信息到条目
        mod_info = {
            "version": version,
            "curseforge_id": cid,
            "slug": slug,
        }

        if entries:
            mod_data_section = {
                "mod_info": mod_info,
                "entries": entries,
            }
            all_entries.extend(entries)

        all_warnings.extend(warnings)

        time.sleep(0.1)  # 限流

    # Step 5: 统计
    en_changed_count = sum(1 for e in all_entries if "old_en" in e)
    zh_changed_count = sum(1 for e in all_entries if "old_zh" in e)
    en_unchanged_zh_changed = sum(1 for e in all_entries if e.get("review_type") == "zh_only_change")
    zh_unchanged_warnings = len(all_warnings)

    result: dict[str, Any] = {
        "repo": repo,
        "pr": pr,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "mods": {},
        "all_entries": all_entries,
        "all_warnings": all_warnings,
        "stats": {
            "total_changed_keys": len(all_entries),
            "en_changed": en_changed_count,
            "zh_changed": zh_changed_count,
            "en_unchanged_zh_changed": en_unchanged_zh_changed,
            "zh_unchanged_warnings": zh_unchanged_warnings,
        },
    }

    # 构建 mods 字段
    for mod_key, mod_data in mods.items():
        mi = mod_data["mod_info"]
        resolved_key = f"{mi['version']}/{mi['curseforge_id']}/{mi['slug']}"
        mod_entries = [e for e in all_entries if resolved_key == mod_key]
        if mod_entries:
            result["mods"][resolved_key] = {
                "mod_info": mi,
                "entries": mod_entries,
            }

    # 保存
    output_path = Path(output_dir) / "00_pr_alignment.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    en_changed = result["stats"]["en_changed"]
    zh_changed = result["stats"]["zh_changed"]
    warnings_count = len(result["all_warnings"])
    print(f"[PR Aligner] 完成: {len(all_entries)} 条变更, "
          f"EN 变更 {en_changed}, ZH 变更 {zh_changed}, "
          f"警告 {warnings_count} 条")
    print(f"  输出: {output_path}")

    return str(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PR 差异对齐器：从 GitHub PR 拉取差异并生成对齐数据"
    )
    parser.add_argument("--repo", required=True,
                        help="GitHub 仓库名，如 CFPAOrg/Minecraft-Mod-Language-Package")
    parser.add_argument("--pr", type=int, required=True,
                        help="PR 编号")
    parser.add_argument("-o", "--output-dir", default="./output",
                        help="输出目录")
    parser.add_argument("--token", default="",
                        help="GitHub Token（可选，公共仓库拉取有限流 60 req/hr）")

    args = parser.parse_args()

    if "/" not in args.repo:
        print("错误: --repo 格式应为 owner/repo", file=sys.stderr)
        sys.exit(1)

    run_pr_aligner(
        repo=args.repo,
        pr=args.pr,
        output_dir=args.output_dir,
        token=args.token,
    )


if __name__ == "__main__":
    main()
