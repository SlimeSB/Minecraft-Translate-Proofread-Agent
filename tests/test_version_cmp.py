"""测试版本号比较工具。"""
import pytest
from src.tools.version_cmp import parse_mc_version, sort_versions_desc, version_le


def test_parse_two_segment():
    assert parse_mc_version("1.21") == (1, 21)


def test_parse_three_segment():
    assert parse_mc_version("1.20.1") == (1, 20, 1)


def test_parse_leading_zero():
    assert parse_mc_version("1.09") == (1, 9)


def test_parse_invalid_empty():
    assert parse_mc_version("") == ()


def test_parse_invalid_legacy():
    assert parse_mc_version("legacy") == ()


def test_parse_invalid_random():
    assert parse_mc_version("abc.def") == ()


def test_sort_desc_standard():
    result = sort_versions_desc(["1.19.2", "1.21", "1.20.1"])
    assert result == ["1.21", "1.20.1", "1.19.2"]


def test_sort_desc_single():
    result = sort_versions_desc(["1.19.2"])
    assert result == ["1.19.2"]


def test_sort_desc_empty():
    assert sort_versions_desc([]) == []


def test_sort_desc_invalid_mixed():
    result = sort_versions_desc(["1.19.2", "invalid", "1.21"])
    assert result[0] == "1.21"
    assert result[1] == "1.19.2"


def test_version_le_smaller():
    assert version_le("1.12.2", "1.16.5") is True


def test_version_le_equal():
    assert version_le("1.12.2", "1.12.2") is True


def test_version_le_larger():
    assert version_le("1.19.2", "1.12.2") is False


def test_version_le_two_segment():
    assert version_le("1.12", "1.12.2") is True


def test_version_le_invalid_a():
    assert version_le("invalid", "1.12.2") is False


def test_version_le_invalid_b():
    assert version_le("1.12.2", "invalid") is False


def test_version_le_both_invalid():
    assert version_le("", "") is False


def test_version_le_two_vs_three_equal():
    assert version_le("1.12", "1.12.0") is True


def test_version_le_three_vs_two():
    assert version_le("1.12.1", "1.12") is False
