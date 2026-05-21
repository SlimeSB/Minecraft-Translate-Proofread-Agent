"""跨版本差异计算。

同一 slug 的多版本数据递归比对——每个低版本与紧邻高版本比对，
输出新增 key 和修改 key 清单，跳过删除 key。
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CrossVersionDiff:
    """单个版本的跨版本差异。"""
    slug: str
    current_version: str
    ref_version: str = ""
    added_keys: list[str] = field(default_factory=list)
    modified_keys: list[str] = field(default_factory=list)
    key_refs: dict[str, dict[str, str]] = field(default_factory=dict)


def compute_cross_version_diff(
    slug: str,
    current_version: str,
    current_full_en: dict[str, str],
    current_full_zh: dict[str, str],
    ref_version: str,
    ref_full_en: dict[str, str],
    ref_full_zh: dict[str, str],
) -> CrossVersionDiff:
    """计算当前版本相对于参考版本的新增和修改 key。

    视角：当前版本有什么和参考版本不同？
    - added_keys: 当前版本有但参考版本没有的 key
    - modified_keys: 两版本都有但 EN 或 ZH 值不同的 key
    - 参考版本有但当前版本没有的 key（删除）跳过
    - 值完全相同的 key 跳过

    参考版本始终是较高版本。
    """
    diff = CrossVersionDiff(slug=slug, current_version=current_version, ref_version=ref_version)

    current_keys = set(current_full_en.keys())
    ref_keys = set(ref_full_en.keys())

    # 新增：当前版本有，参考版本没有
    for k in sorted(current_keys - ref_keys):
        diff.added_keys.append(k)

    # 修改：两版本都有但值不同
    for k in sorted(current_keys & ref_keys):
        en_diff = current_full_en.get(k, "") != ref_full_en.get(k, "")
        zh_diff = current_full_zh.get(k, "") != ref_full_zh.get(k, "")
        if en_diff or zh_diff:
            diff.modified_keys.append(k)
            diff.key_refs[k] = {
                "ref_en": ref_full_en.get(k, ""),
                "ref_zh": ref_full_zh.get(k, ""),
                "ref_version": ref_version,
            }

    return diff


def compute_all_cross_version_diffs(
    slug: str,
    sorted_versions: list[str],
    full_data: dict[str, tuple[dict[str, str], dict[str, str]]],
) -> dict[str, CrossVersionDiff]:
    """为所有低版本计算跨版本差异（最高版本无差异）。

    full_data: {version: (full_en, full_zh)}
    返回: {version: CrossVersionDiff}，不含最高版本
    """
    results: dict[str, CrossVersionDiff] = {}
    if len(sorted_versions) < 2:
        return results

    for i in range(1, len(sorted_versions)):
        current_ver = sorted_versions[i]
        ref_ver = sorted_versions[i - 1]
        cur_en, cur_zh = full_data.get(current_ver, ({}, {}))
        ref_en, ref_zh = full_data.get(ref_ver, ({}, {}))

        diff = compute_cross_version_diff(
            slug=slug,
            current_version=current_ver,
            current_full_en=cur_en,
            current_full_zh=cur_zh,
            ref_version=ref_ver,
            ref_full_en=ref_en,
            ref_full_zh=ref_zh,
        )
        results[current_ver] = diff

    return results
