"""
持久化词形缓存（持续学习）。

每次 LLM 裁决后写入缓存，下次直接复用，减少 LLM 调用。

内部：{variant_lower: canonical} + {canonical_lower: freq}
磁盘（按频次降序）：
{
  "one": { "variants": ["one", "ones"], "freq": 6 }
}
"""
import json
from pathlib import Path
from typing import Any

DEFAULT_CACHE_PATH = "lemma_cache.json"


class LemmaCache:
    """持久化词形映射缓存。"""

    def __init__(self, path: str = DEFAULT_CACHE_PATH):
        self.path = Path(path)
        self.map: dict[str, str] = {}       # {variant_lower: canonical}
        self._freq: dict[str, int] = {}     # {canonical_lower: cumulative freq}
        self._contrib: dict[str, int] = {}  # {variant_lower: lookup count for current mapping}
        self._loaded = False

    def load(self) -> dict[str, str]:
        if self._loaded:
            return self.map
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.map.clear()
                self._freq.clear()
                for canonical, entry in data.items():
                    canon_lower = canonical.lower().strip()
                    freq = entry.get("freq", 0)
                    self._freq[canon_lower] = max(self._freq.get(canon_lower, 0), freq)
                    variants = entry.get("variants", [canonical])
                    for v in variants:
                        vk = v.lower().strip()
                        if vk not in self.map:
                            self.map[vk] = canonical
            except (json.JSONDecodeError, IOError):
                self.map = {}
                self._freq = {}
        self._loaded = True
        return self.map

    def save(self) -> None:
        """按频次降序写入分组格式。"""
        canonicals: dict[str, list[str]] = {}
        for variant_lower, canonical in self.map.items():
            canon_lower = canonical.lower().strip()
            canonicals.setdefault(canon_lower, []).append(variant_lower)

        entries: list[tuple[int, str, dict[str, Any]]] = []
        for canon_lower, variant_list in canonicals.items():
            freq = self._freq.get(canon_lower, 0)
            display_canon = self.map.get(canon_lower, canon_lower)
            variants_sorted = sorted(
                set(variant_list),
                key=lambda v: (len(v), v),
            )
            entries.append((freq, display_canon, {
                "variants": variants_sorted,
                "freq": freq,
            }))

        entries.sort(key=lambda x: (-x[0], x[1]))

        result = {canon: content for _, canon, content in entries}

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    def lookup(self, term: str) -> str | None:
        """查缓存：已知 variant 返回 canonical，否则 None。"""
        key = term.lower().strip()
        canon = self.map.get(key)
        if canon is not None:
            canon_lower = canon.lower().strip()
            self._freq[canon_lower] = self._freq.get(canon_lower, 0) + 1
            self._contrib[key] = self._contrib.get(key, 0) + 1
            return canon
        return None

    def record(self, canonical: str, members: list[str], source: str = "llm") -> None:
        """写入一批映射并保存。"""
        canon_key = canonical.lower().strip()
        # 更新 canonical 自身
        self.map[canon_key] = canonical
        self._freq[canon_key] = self._freq.get(canon_key, 0) + 1
        self._contrib[canon_key] = self._contrib.get(canon_key, 0) + 1

        for m in members:
            mk = m.lower().strip()
            if mk == canon_key:
                continue
            if mk in self.map:
                old_canon = self.map[mk].lower().strip()
                if old_canon in self._freq:
                    # 从旧 canonical 减去该 variant 的实际贡献次数
                    contrib = self._contrib.pop(mk, 1)
                    self._freq[old_canon] = max(0, self._freq.get(old_canon, 0) - contrib)
            self.map[mk] = canonical
            self._contrib[mk] = self._contrib.get(mk, 0) + 1
            self._freq[canon_key] = self._freq.get(canon_key, 0) + 1

        self.save()

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(set(self.map.values())),
            "variants": len(self.map),
            "path": str(self.path),
        }
