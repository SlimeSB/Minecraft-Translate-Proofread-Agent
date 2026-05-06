"""PR 审校 — GitHub API / raw 文件拉取。"""
import json
import time
import urllib.error
import urllib.request
from typing import Any

_USER_AGENT = "Mozilla/5.0 (compatible; MinecraftTranslateProofreadAgent/1.0)"
_TOKEN_WARNED = False


def _token_warning():
    global _TOKEN_WARNED
    if not _TOKEN_WARNED:
        _TOKEN_WARNED = True
        print("  ⚠ GITHUB_TOKEN 无效，已降级为未认证请求（限流 60 req/hr）")
        print("  建议申请 Personal Access Token（classic）填入 .env 的 GITHUB_TOKEN")
        print("  注意：仓库管理要求 token 有效期 ≤ 365 天，过期后需重新生成")


def build_headers(token: str = "") -> dict[str, str]:
    headers: dict[str, str] = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _try_with_fallback(fn, token: str) -> Any:
    """先带 token 请求，401/403 时降级为无 token 重试。"""
    if not token:
        return fn("")
    try:
        return fn(token)
    except RuntimeError as e:
        msg = str(e)
        if "401" in msg or "403" in msg and "rate limit" not in msg.lower():
            _token_warning()
            return fn("")
        raise


def api_get(url: str, token: str = "") -> Any:
    def _do(t: str) -> Any:
        req = urllib.request.Request(url, headers=build_headers(t))
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API 错误 {e.code}: {body}") from e

    return _try_with_fallback(_do, token)


def raw_get(url: str, token: str = "", retries: int = 3) -> str:
    def _do_one(t: str) -> str:
        headers = build_headers(t)
        u = url
        if t:
            u += f"?token={t}"
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(u, headers=headers)
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

    return _try_with_fallback(_do_one, token)
