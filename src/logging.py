"""薄日志封装层，统一项目内 print()/sys.stderr 混用问题。

用法:
    from src.logging import info, warn, error, debug
    info("Phase 1 完成")
    warn("LLM 调用异常: timeout")
    error("API 密钥未设置")
    debug("详细诊断信息（上线后由 --verbose 控制输出）")
"""
import sys


def info(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print(msg, file=sys.stderr)


def error(msg: str) -> None:
    print(msg, file=sys.stderr)


def debug(msg: str) -> None:
    # TODO: 上线后由 --verbose CLI 参数控制，当前开发阶段全量输出
    print(msg)
