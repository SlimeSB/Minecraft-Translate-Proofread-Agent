"""Minecraft 版本号比较工具。

解析 major.minor[.patch] 格式，支持排序和 ≤ 比较。
"""
import re

_VER_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_mc_version(version: str) -> tuple[int, ...]:
    """将 Minecraft 版本号字符串解析为整数元组。

    返回空元组 () 表示非法版本号。
    """
    m = _VER_RE.match(version.strip())
    if not m:
        return ()
    major = int(m.group(1))
    minor = int(m.group(2))
    patch_str = m.group(3)
    if patch_str is not None:
        return (major, minor, int(patch_str))
    return (major, minor)


def sort_versions_desc(versions: list[str]) -> list[str]:
    """按版本号降序排列字符串列表。非法版本号排最后。"""
    return sorted(versions, key=lambda v: parse_mc_version(v) or (0,), reverse=True)


def version_le(a: str, b: str) -> bool:
    """判断 a ≤ b（用于 vanilla terms scope 匹配）。"""
    pa = parse_mc_version(a)
    pb = parse_mc_version(b)
    if not pa or not pb:
        return False
    for i in range(max(len(pa), len(pb))):
        va = pa[i] if i < len(pa) else 0
        vb = pb[i] if i < len(pb) else 0
        if va < vb:
            return True
        if va > vb:
            return False
    return True
