"""测试跨版本差异计算。"""
import pytest
from src.tools.pr.cross_version_diff import (
    CrossVersionDiff,
    compute_cross_version_diff,
    compute_all_cross_version_diffs,
)


def test_added_key():
    """1.20.1 有 diamond_chest 但 1.21 没有 → added"""
    en_1201 = {"ironchest:iron_chest": "Iron Chest", "ironchest:diamond_chest": "Diamond Chest"}
    zh_1201 = {"ironchest:iron_chest": "铁箱子", "ironchest:diamond_chest": "钻石箱子"}
    en_121 = {"ironchest:iron_chest": "Iron Chest"}
    zh_121 = {"ironchest:iron_chest": "铁箱子"}

    diff = compute_cross_version_diff(
        "ironchest", "1.20.1", en_1201, zh_1201,
        "1.21", en_121, zh_121,
    )
    assert "ironchest:diamond_chest" in diff.added_keys
    assert "ironchest:diamond_chest" not in diff.modified_keys
    assert "ironchest:diamond_chest" not in diff.key_refs


def test_modified_key():
    """两版本都有但 EN/ZH 值不同 → modified"""
    en_1201 = {"ironchest:iron_chest": "Iron Chest"}
    zh_1201 = {"ironchest:iron_chest": "铁质箱子"}
    en_121 = {"ironchest:iron_chest": "Iron Chest"}
    zh_121 = {"ironchest:iron_chest": "铁箱子"}

    diff = compute_cross_version_diff(
        "ironchest", "1.20.1", en_1201, zh_1201,
        "1.21", en_121, zh_121,
    )
    assert "ironchest:iron_chest" in diff.modified_keys
    assert diff.key_refs["ironchest:iron_chest"]["ref_zh"] == "铁箱子"
    assert diff.key_refs["ironchest:iron_chest"]["ref_version"] == "1.21"


def test_deleted_key_skipped():
    """高版本有低版本没有的 key → 跳过（不放入 added/modified）"""
    en_1201 = {"ironchest:iron_chest": "Iron Chest"}
    zh_1201 = {"ironchest:iron_chest": "铁箱子"}
    en_121 = {"ironchest:iron_chest": "Iron Chest", "ironchest:silver_chest": "Silver Chest"}
    zh_121 = {"ironchest:iron_chest": "铁箱子", "ironchest:silver_chest": "银箱子"}

    diff = compute_cross_version_diff(
        "ironchest", "1.20.1", en_1201, zh_1201,
        "1.21", en_121, zh_121,
    )
    assert "ironchest:silver_chest" not in diff.added_keys
    assert "ironchest:silver_chest" not in diff.modified_keys


def test_same_values_skipped():
    """两版本值完全相同 → 跳过"""
    en_1201 = {"ironchest:iron_chest": "Iron Chest"}
    zh_1201 = {"ironchest:iron_chest": "铁箱子"}
    en_121 = {"ironchest:iron_chest": "Iron Chest"}
    zh_121 = {"ironchest:iron_chest": "铁箱子"}

    diff = compute_cross_version_diff(
        "ironchest", "1.20.1", en_1201, zh_1201,
        "1.21", en_121, zh_121,
    )
    assert len(diff.added_keys) == 0
    assert len(diff.modified_keys) == 0


def test_three_version_recursive():
    """三版本：1.21（最高无diff），1.20.1 diff 1.21，1.19.2 diff 1.20.1"""
    en_121 = {"a:one": "One"}
    zh_121 = {"a:one": "一"}
    en_1201 = {"a:one": "One", "a:two": "Two"}
    zh_1201 = {"a:one": "壹", "a:two": "二"}
    en_1192 = {"a:one": "One", "a:two": "Two", "a:three": "Three"}
    zh_1192 = {"a:one": "一", "a:two": "二", "a:three": "三"}

    full_data = {
        "1.21": (en_121, zh_121),
        "1.20.1": (en_1201, zh_1201),
        "1.19.2": (en_1192, zh_1192),
    }
    diffs = compute_all_cross_version_diffs(
        "test", ["1.21", "1.20.1", "1.19.2"], full_data,
    )

    assert "1.21" not in diffs

    diff_1201 = diffs["1.20.1"]
    assert "a:two" in diff_1201.added_keys
    assert "a:one" in diff_1201.modified_keys
    assert diff_1201.key_refs["a:one"]["ref_version"] == "1.21"

    diff_1192 = diffs["1.19.2"]
    assert diff_1192.key_refs["a:one"]["ref_version"] == "1.20.1"


def test_single_version_no_diff():
    """单版本没有跨版本差异"""
    diffs = compute_all_cross_version_diffs(
        "single", ["1.21"], {"1.21": ({}, {})},
    )
    assert len(diffs) == 0


def test_empty_data():
    """空数据边界"""
    diff = compute_cross_version_diff("test", "1.20.1", {}, {}, "1.21", {}, {})
    assert len(diff.added_keys) == 0
    assert len(diff.modified_keys) == 0


def test_en_only_changed():
    """仅 EN 变化也标记为 modified"""
    en_1201 = {"key": "New Text"}
    zh_1201 = {"key": "文本"}
    en_121 = {"key": "Old Text"}
    zh_121 = {"key": "文本"}

    diff = compute_cross_version_diff(
        "test", "1.20.1", en_1201, zh_1201,
        "1.21", en_121, zh_121,
    )
    assert "key" in diff.modified_keys
    assert diff.key_refs["key"]["ref_en"] == "Old Text"
