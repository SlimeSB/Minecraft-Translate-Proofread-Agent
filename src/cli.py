"""CLI 工具函数 —— 被 run.py 使用。"""
import json
import os
import sys


def load_dotenv(path: str = ".env") -> None:
    """加载 .env 文件中的环境变量（不覆盖已有值）。"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v


def configure_utf8_output() -> None:
    """强制 UTF-8 输出（兼容 Windows GBK 终端）。"""
    if sys.stdout.encoding != "utf-8" and sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def safe_print(*args, **kwargs) -> None:
    """GBK 安全打印。"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        for a in args:
            print(str(a).encode(enc, errors="replace").decode(enc), **kwargs)


def check_api_health(base_url: str, api_key: str) -> bool:
    """启动前检查 API 可用性。成功返回 True。"""
    import urllib.error
    import urllib.request

    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]

    models_url = base_url + "/models"
    headers = {"User-Agent": "MinecraftTranslateProofreadAgent/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(models_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                safe_print(f"  [OK] API 连接正常: {base_url}")
                return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            safe_print(f"  [FAIL] API Key 无效 (401): {base_url}")
            return False
        elif e.code == 403:
            safe_print(f"  [FAIL] API 访问被拒绝 (403): {base_url}")
            return False
    except Exception as e:
        safe_print(f"  [FAIL] API 不可达: {base_url} -- {e}")
        return False

    chat_url = base_url + "/chat/completions"
    body = json.dumps({
        "model": os.environ.get("REVIEW_OPENAI_MODEL", "deepseek-v4-flash"),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode("utf-8")
    headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(chat_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                safe_print(f"  [OK] API 可用: {base_url}")
                return True
            body_text = resp.read().decode("utf-8", errors="replace")
            if "invalid" in body_text.lower():
                safe_print(f"  [FAIL] API Key 无效: {base_url}")
                return False
            safe_print(f"  [OK] API 连接正常: {base_url}")
            return True
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:200]
        safe_print(f"  [FAIL] API 请求失败 ({e.code}): {body_text}")
        return False
    except Exception as e:
        safe_print(f"  [FAIL] API 不可达: {base_url} -- {e}")
        return False
