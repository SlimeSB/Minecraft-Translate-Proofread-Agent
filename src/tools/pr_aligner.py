"""PR 差异对齐器（兼容入口，实际逻辑在 src/tools/pr/）。"""
import argparse
import sys

from src.tools.pr import run_pr_aligner

# 向后兼容：旧代码可能直接 import 这些
from src.tools.pr._http import api_get as _api_get, raw_get as _raw_get


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PR 差异对齐器：从 GitHub PR 拉取差异并生成对齐数据"
    )
    parser.add_argument("--repo", required=True,
                        help="GitHub 仓库名，如 CFPAOrg/Minecraft-Mod-Language-Package")
    parser.add_argument("--pr", type=int, required=True, help="PR 编号")
    parser.add_argument("-o", "--output-dir", default="./output", help="输出目录")
    parser.add_argument("--token", default="",
                        help="GitHub Token（可选，公共仓库限流 60 req/hr）")

    args = parser.parse_args()

    if "/" not in args.repo:
        print("错误: --repo 格式应为 owner/repo", file=sys.stderr)
        sys.exit(1)

    run_pr_aligner(
        repo=args.repo,
        pr=args.pr,
        output_dir=args.output_dir,
        token=args.token,
    )


if __name__ == "__main__":
    main()
