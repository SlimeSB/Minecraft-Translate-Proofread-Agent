"""PR 审校 — GitHub API / raw 文件拉取。"""
import json
import time
import urllib.error
import urllib.request
from typing import Any

_USER_AGENT = "Mozilla/5.0 (compatible; MinecraftTranslateProofreadAgent/1.0)"


def build_headers(token: str = "") -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def api_get(url: str, token: str = "") -> Any:
    req = urllib.request.Request(url, headers=build_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API 错误 {e.code}: {body}") from e


def raw_get(url: str, token: str = "", retries: int = 3) -> str:
    headers = build_headers(token)
    if token:
        url += f"?token={token}"
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            timeout = 30 * attempt
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Raw 文件错误 {e.code}: {body}") from e
        except (TimeoutError, urllib.error.URLError) as e:
            last_err = e
            if attempt < retries:
                wait = attempt * 2
                print(f"  [重试 {attempt}/{retries}] {url.split('/')[-1]} 超时，{wait}s 后重试...")
                time.sleep(wait)
    raise RuntimeError(f"Raw 文件拉取失败（重试{retries}次）: {last_err}")
