"""共用代码/专有名词检测，统一 is_likely_code_or_proper_noun() 实现。

用法:
    from src.tools.code_detection import is_likely_code_or_proper_noun
    result = is_likely_code_or_proper_noun("BLOCK_OF_GOLD")  # True
"""
import re

NON_TRANSLATABLE_PATTERNS = [
    re.compile(r"^[A-Z_]+$"),
    re.compile(r"^[0-9]+$"),
    re.compile(r"^[A-Za-z0-9_.-]+$"),
    re.compile(r"^§[0-9a-fA-F].*"),
    re.compile(r"^%[a-zA-Z0-9_.$]*$"),
    re.compile(r"^\{[^{}]*\}$"),
    re.compile(r"^%[A-Za-z_]\w*%$"),
]


def is_likely_code_or_proper_noun(text: str) -> bool:
    for pat in NON_TRANSLATABLE_PATTERNS:
        if pat.match(text.strip()):
            return True
    return False
