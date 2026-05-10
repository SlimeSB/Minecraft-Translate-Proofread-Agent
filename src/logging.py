"""薄日志封装层，统一项目内 print()/sys.stderr 混用问题。

用法:
    from src.logging import info, warn, error
    info("Phase 1 完成")
    warn("LLM 调用异常: timeout")
    error("API 密钥未设置")
"""
import sys


def info(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print(msg, file=sys.stderr)


def error(msg: str) -> None:
    print(msg, file=sys.stderr)
