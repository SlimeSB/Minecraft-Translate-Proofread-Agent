"""从 i18n-Dict-Extender 社区仓库下载外部翻译词典。

用法:
    python scripts/download_external_dict.py
    python scripts/download_external_dict.py --repo VM-Chinese-translate-group/i18n-Dict-Extender --output data/Dict-Sqlite.db

要求:
    - GITHUB_TOKEN 环境变量（避免 API 限流，60 req/hr 未认证）
    - Python 3.11+
"""
import argparse
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_REPO = "VM-Chinese-translate-group/i18n-Dict-Extender"
DEFAULT_OUTPUT = "data/Dict-Sqlite.db"


def get_latest_release_asset(repo: str, token: str = "") -> tuple[str, str, int]:
    """返回 (download_url, filename, size_bytes)。"""
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"User-Agent": "MinecraftTranslateProofreadAgent/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(api_url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        import json
        release = json.loads(resp.read().decode("utf-8"))
    assets = release.get("assets", [])
    db_assets = [a for a in assets if a["name"].endswith(".db")]
    if not db_assets:
        raise RuntimeError(f"最新 release 中未找到 .db 文件: {[a['name'] for a in assets][:5]}")
    asset = db_assets[0]
    return asset["browser_download_url"], asset["name"], asset["size"]


def download_file(url: str, dest: Path, expected_size: int, token: str = "") -> None:
    headers = {"User-Agent": "MinecraftTranslateProofreadAgent/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0)) or expected_size
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                pct = downloaded * 100 // total if total else 0
                print(f"\r  下载中... {downloaded // 1048576}MB / {total // 1048576}MB ({pct}%)", end="", flush=True)
        print()
    if dest.stat().st_size < 1024:
        raise RuntimeError(f"下载文件异常（{dest.stat().st_size} 字节），请检查 URL 或 Token")


def main() -> None:
    parser = argparse.ArgumentParser(description="下载外部社区翻译词典")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub 仓库名（org/repo）")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="输出路径")
    parser.add_argument("--token", default="", help="GitHub Token（可选，也可设 GITHUB_TOKEN 环境变量）")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("提示: 未设置 GITHUB_TOKEN，API 限流 60 req/hr。建议设置环境变量或 --token。")

    print(f"查询 {args.repo} 最新 release...")
    try:
        url, filename, size = get_latest_release_asset(args.repo, token)
    except urllib.error.HTTPError as e:
        print(f"错误: GitHub API 返回 {e.code}（检查仓库名和 Token）", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  文件: {filename} ({size // 1048576}MB)")
    dest = Path(args.output)
    if dest.exists():
        print(f"输出文件已存在: {dest}")
        print(f"跳过下载（如需重新下载请先删除该文件）")
        sys.exit(0)
    print(f"下载 → {dest}")
    try:
        download_file(url, dest, size, token)
    except Exception as e:
        if dest.exists():
            dest.unlink()
        print(f"下载失败: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"完成: {dest} ({dest.stat().st_size // 1048576}MB)")


if __name__ == "__main__":
    main()
