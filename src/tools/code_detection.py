"""共用代码/专有名词检测，统一 is_likely_code_or_proper_noun() 实现。

用法:
    from src.tools.code_detection import is_likely_code_or_proper_noun
    result = is_likely_code_or_proper_noun("BLOCK_OF_GOLD")  # True
"""
import re

from src import config as cfg


def _compile_patterns() -> list[re.Pattern]:
    return [re.compile(p) for p in cfg.NON_TRANSLATABLE_PATTERNS]


_NON_TRANSLATABLE_PATTERNS: list[re.Pattern] = _compile_patterns()


def is_likely_code_or_proper_noun(text: str) -> bool:
    for pat in _NON_TRANSLATABLE_PATTERNS:
        if pat.match(text.strip()):
            return True
    return False
