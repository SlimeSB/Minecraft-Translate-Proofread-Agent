"""从 data/Minecraft.db 提取术语，输出 JSON 术语库。

用法:
    python scripts/extract_terms_from_db.py [--min-freq 5] [--output 术语库.json]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

# 确保能找到项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.checkers.terminology_builder import TerminologyBuilder
from src.models import AlignmentDict
from src import config as cfg
from src.logging import info


def main():
    parser = argparse.ArgumentParser(description="从 Minecraft.db 自动提取术语")
    parser.add_argument("--db", default="data/Minecraft.db", help="db 路径")
    parser.add_argument("--min-freq", type=int, default=5, help="术语最低频次")
    parser.add_argument("--output", default="output/术语库.json", help="输出 JSON 路径")
    args = parser.parse_args()

    # 1. 从 db 读取数据
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"错误: 未找到 {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT key, en_us, zh_cn FROM vanilla_keys WHERE zh_cn IS NOT NULL AND zh_cn != ''"
    ).fetchall()
    conn.close()

    print(f"从 db 读取 {len(rows)} 条有中文的条目")

    # 2. 构建数据
    en_data: dict[str, str] = {}
    zh_data: dict[str, str] = {}
    matched_entries: list[dict] = []

    for r in rows:
        k = r["key"]
        en_v = (r["en_us"] or "").strip()
        zh_v = (r["zh_cn"] or "").strip()
        if not k or not en_v:
            continue
        en_data[k] = en_v
        zh_data[k] = zh_v
        matched_entries.append({"key": k, "en": en_v, "zh": zh_v})

    print(f"有效条目: {len(matched_entries)} 条")

    # 3. 构造 alignment
    alignment: AlignmentDict = {
        "matched_entries": matched_entries,
        "stats": {
            "matched": len(matched_entries),
            "missing_zh": 0,
            "extra_zh": 0,
            "suspicious_untranslated": 0,
            "total_en": len(en_data),
            "total_zh": len(zh_data),
        },
    }

    # 4. 术语提取
    tb = TerminologyBuilder()
    tb.load(en_data, zh_data, alignment)

    print("提取候选术语...")
    tb.extract(min_freq=args.min_freq)

    print("归并词形...")
    tb.merge_lemmas(llm_call=None)  # 纯算法归并，不用 LLM

    print("构建术语表...")
    glossary = tb.build_glossary(min_freq=args.min_freq)

    # 5. 输出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成！共提取 {len(glossary)} 条术语")
    print(f"   输出到: {output_path.resolve()}")

    # 打印前 20 条看看
    print("\n前 20 条术语预览:")
    print("-" * 50)
    for i, g in enumerate(glossary[:20]):
        print(f"  {i+1:3d}. {g['en']:40s} → {g['zh']}")


if __name__ == "__main__":
    main()
