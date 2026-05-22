"""薄日志封装层，统一项目内 print()/sys.stderr 混用问题。

info/warn/error 同时输出到控制台和 logs/latest.log。
debug 仅写入 logs/latest.log，不输出到控制台。

用法:
    from src.logging import info, warn, error, debug
    info("Phase 1 完成")
    warn("LLM 调用异常: timeout")
    error("API 密钥未设置")
    debug("详细诊断信息")
"""
import datetime
import sys
import time
import threading
from pathlib import Path

_LOG_DIR = Path("logs")
_LOG_PATH = _LOG_DIR / "latest.log"
_SETUP_DONE = False
_LOCK = threading.Lock()


def _safe_print(msg: str, file=sys.stdout) -> None:
    """GBK 安全打印，Windows 终端 emoji 兼容。"""
    try:
        print(msg, file=file)
    except UnicodeEncodeError:
        out = file.buffer if hasattr(file, "buffer") else sys.stdout.buffer
        out.write(msg.encode("utf-8", errors="replace") + b"\n")
        out.flush()


def _setup_file_log() -> None:
    global _SETUP_DONE
    if _SETUP_DONE:
        return
    _SETUP_DONE = True
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    if _LOG_PATH.exists() and _LOG_PATH.stat().st_size > 0:
        mtime = _LOG_PATH.stat().st_mtime
        archive_name = time.strftime("%Y-%m-%d-%H%M%S", time.localtime(mtime))
        _LOG_PATH.rename(_LOG_DIR / f"latest.{archive_name}.log")


def _write_file(level: str, msg: str) -> None:
    _setup_file_log()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}\n"
    with _LOCK, open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def log_to_file(level: str, msg: str) -> None:
    """仅写入文件，不输出到控制台。供其他模块（如 LLM client）使用。"""
    _write_file(level, msg)


def info(msg: str) -> None:
    _safe_print(msg)
    _write_file("INFO", msg)


def warn(msg: str) -> None:
    _safe_print(msg, file=sys.stderr)
    _write_file("WARN", msg)


def error(msg: str) -> None:
    _safe_print(msg, file=sys.stderr)
    _write_file("ERROR", msg)


def debug(msg: str) -> None:
    _write_file("DEBUG", msg)
