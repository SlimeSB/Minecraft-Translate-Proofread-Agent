"""外部词典模块 — 从 data/Dict-Sqlite.db 加载社区翻译参考，注入 LLM 提示词。"""
from src.dictionary.external import ExternalDictStore

__all__ = ["ExternalDictStore"]
