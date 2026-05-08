"""从 Minecraft 原版 en_us.json 提取全部 key 写入 data/vanilla_keys.json。

用法:
    python scripts/extract_vanilla_keys.py path/to/minecraft/en_us.json [--version 1.21.4]

来源:
    各版本 Minecraft 的 en_us.json 可从以下途径获取:
    - 游戏目录: .minecraft/assets/objects/ 下查找（需 hash 反查）
    - 官方资源: https://mcassets.cloud/mod/1.21.4/assets/minecraft/lang/en_us.json
    - Wiki: https://minecraft.wiki/w/Resource_location 相关页面
"""
import argparse
import json
import sys
from pathlib import Path


def extract_keys(en_us_path: str, version: str) -> dict:
    with open(en_us_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    keys = sorted(data.keys())
    return {
        "_note": "Minecraft 原版英文语言文件的所有 key。用于检测模组是否覆盖了原版 key。",
        "_source": "从 Minecraft en_us.json 提取",
        "_version": version,
        "keys": keys,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从 Minecraft en_us.json 提取原版 key 列表")
    parser.add_argument("en_us", help="Minecraft 原版 en_us.json 路径")
    parser.add_argument("--version", default="1.21.4", help="Minecraft 版本号")
    parser.add_argument("--output", default="data/vanilla_keys.json", help="输出路径")
    args = parser.parse_args()

    en_path = Path(args.en_us)
    if not en_path.exists():
        print(f"错误: 文件不存在: {en_path}", file=sys.stderr)
        sys.exit(1)

    result = extract_keys(str(en_path), args.version)
    key_count = len(result["keys"])

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"已提取 {key_count} 个原版 key → {out_path}")


if __name__ == "__main__":
    main()
