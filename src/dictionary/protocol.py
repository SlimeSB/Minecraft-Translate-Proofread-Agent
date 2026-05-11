"""DictStore Protocol — 所有词典存储的统一接口。"""

from typing import Any, Protocol


class LookupMode:
    MIXED = "mixed"
    SHORT = "short"


class DictStore(Protocol):
    def lookup(self, en_text: str, mode: str = LookupMode.MIXED, **kwargs: Any) -> str: ...

    def load(self) -> None: ...

    def close(self) -> None: ...
