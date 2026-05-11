"""版本比较工具。"""


def parse_version(v: str) -> tuple[int, ...]:
    parts = v.split(".")
    return tuple(int(p) for p in parts)
