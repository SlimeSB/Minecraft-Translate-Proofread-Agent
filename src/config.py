"""全局配置模块。所有模块从这里取配置，避免重复。"""
import json
from typing import Any

CONFIG_PATH = "review_config.json"

_cfg_cache: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _cfg_cache
    if _cfg_cache is None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                _cfg_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _cfg_cache = {}
    return _cfg_cache


def get(key: str, default: Any = None) -> Any:
    return _load().get(key, default)


# ── 常用配置项 ──

DESC_KEY_SUFFIXES: tuple[str, ...] = tuple(
    get("desc_key_suffixes", [".desc", ".description", ".lore", ".tooltip",
                               ".flavor", ".info", ".message", ".text"])
)

TERM_MIN_FREQ = get("term_min_freq", 5)
TERM_MIN_CONSENSUS = get("term_min_consensus", 0.6)
TERM_MAX_ZH_LEN = get("term_max_zh_len", 40)
TERM_MAX_EN_LEN = get("term_max_en_len", 60)
TERM_CONSENSUS_MIN_TOTAL = get("term_consensus_min_total", 3)
FUZZY_CLUSTER_THRESHOLD = get("fuzzy_cluster_threshold", 65.0)
FUZZY_CLUSTER_TOP_N = get("fuzzy_cluster_top_n", 200)
