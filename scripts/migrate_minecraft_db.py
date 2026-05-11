"""迁移 Minecraft.db 从 (key, version) 每行格式 到 (key, version_start, version_end, changes) 格式。

原格式:
    key | en_us | zh_cn | version | category
    attribute.name.generic.armor | Armor | 盔甲 | 1.12.2 | lang

目标格式:
    key | en_us | zh_cn | version_start | version_end | category | changes
    attribute.name.generic.armor | Armor | 盔甲 | 1.12.2 | 1.16.5 | lang | 1

合并规则: 相邻版本 en_us 和 zh_cn 均未变则合并为一行；任一变化则切新行。
changes: 该 key 在全部版本中发生过变更则为 1，始终未变为 0。

用法:
    python scripts/migrate_minecraft_db.py [--db data/Minecraft.db]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

from src.tools.version_utils import parse_version as _parse_version


def migrate(db_path: str) -> None:
    src = Path(db_path)
    if not src.exists():
        print(f"错误: {src} 不存在", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(src))
    conn.row_factory = sqlite3.Row

    # 1. 读取全部数据
    rows = conn.execute("SELECT key, en_us, zh_cn, version, category FROM translations").fetchall()
    print(f"读取 {len(rows)} 条记录")

    # 2. 按 (key, category) 分组，组内按版本排序
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        gk = (r["key"], r["category"])
        groups.setdefault(gk, []).append({
            "key": r["key"],
            "en_us": r["en_us"],
            "zh_cn": r["zh_cn"],
            "version": r["version"],
            "category": r["category"],
        })

    for gk, entries in groups.items():
        entries.sort(key=lambda e: _parse_version(e["version"]))

    # 3. 合并: en_us 和 zh_cn 均未变才合并，任一变化则切新行
    merged: list[tuple[str, str, str, str, str, str, int]] = []
    for gk, entries in sorted(groups.items()):
        key, category = gk
        # 判断整体是否发生过变化
        changed = False
        for i in range(1, len(entries)):
            prev = entries[i - 1]
            curr = entries[i]
            if prev["en_us"] != curr["en_us"] or prev["zh_cn"] != curr["zh_cn"]:
                changed = True
                break
        changes = 1 if changed else 0

        # 合并连续相同 (en_us, zh_cn) 的行
        run_start = entries[0]
        for i in range(1, len(entries)):
            prev = entries[i - 1]
            curr = entries[i]
            if curr["en_us"] != prev["en_us"] or curr["zh_cn"] != prev["zh_cn"]:
                merged.append((
                    key, run_start["en_us"], run_start["zh_cn"],
                    run_start["version"], prev["version"],
                    category, changes,
                ))
                run_start = curr
        # 最后一个 run
        merged.append((
            key, run_start["en_us"], run_start["zh_cn"],
            run_start["version"], entries[-1]["version"],
            category, changes,
        ))

    print(f"合并后 {len(merged)} 条记录")

    # 4. 创建新表
    conn.execute("DROP TABLE IF EXISTS vanilla_keys")
    conn.execute("""
        CREATE TABLE vanilla_keys (
            key TEXT NOT NULL,
            en_us TEXT,
            zh_cn TEXT,
            version_start TEXT NOT NULL,
            version_end TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'lang',
            changes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (key, version_start, category)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_vanilla_keys_key ON vanilla_keys(key)")

    # 5. 插入数据
    conn.executemany(
        "INSERT INTO vanilla_keys (key, en_us, zh_cn, version_start, version_end, category, changes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        merged,
    )

    # 6. 删旧表
    conn.execute("DROP TABLE translations")
    conn.commit()

    # 7. 统计
    changed = conn.execute(
        "SELECT COUNT(*) FROM vanilla_keys WHERE changes = 1"
    ).fetchone()[0]
    unchanged = conn.execute(
        "SELECT COUNT(*) FROM vanilla_keys WHERE changes = 0"
    ).fetchone()[0]
    unique_keys = conn.execute(
        "SELECT COUNT(DISTINCT key) FROM vanilla_keys"
    ).fetchone()[0]

    print(f"完成: {unique_keys} 个唯一 key")
    print(f"  changes=1: {changed} 条 | changes=0: {unchanged} 条")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 Minecraft.db 格式")
    parser.add_argument("--db", default="data/Minecraft.db", help="数据库路径")
    args = parser.parse_args()
    migrate(args.db)


if __name__ == "__main__":
    main()
