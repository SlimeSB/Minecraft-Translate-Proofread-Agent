"""测试 MinecraftDictStore — load/lookup 两种模式/changes=0 择优/changes=1 全量/排序/版本匹配/边界情况。"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.dictionary.minecraft_dict import MinecraftDictStore


def _create_test_db(path: str) -> None:
    conn = sqlite3.connect(path)
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
    conn.close()


def _insert(conn: sqlite3.Connection, key: str, en: str, zh: str,
            v_start: str, v_end: str, changes: int = 0) -> None:
    conn.execute(
        "INSERT INTO vanilla_keys (key, en_us, zh_cn, version_start, version_end, category, changes) "
        "VALUES (?, ?, ?, ?, ?, 'lang', ?)",
        (key, en, zh, v_start, v_end, changes),
    )


class TestMinecraftDictStore(unittest.TestCase):

    def _make_store_and_conn(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        _create_test_db(path)
        conn = sqlite3.connect(path)
        return path, conn, MinecraftDictStore(db_path=path)

    # 2.8: DB 不存在时静默
    def test_db_not_exists(self):
        store = MinecraftDictStore(db_path="/nonexistent/path_xyz.db")
        store.load()
        result = store.lookup("stone")
        self.assertEqual(result, "")

    # 2.4: 空结果
    def test_empty_result(self):
        path, conn, store = self._make_store_and_conn()
        try:
            conn.close()
            store.load()
            result = store.lookup("zzzznotexist")
            self.assertEqual(result, "")
        finally:
            store.close()
            Path(path).unlink(missing_ok=True)

    # 2.4: 空查询词
    def test_empty_query(self):
        path, conn, store = self._make_store_and_conn()
        try:
            store.load()
            result = store.lookup("")
            self.assertEqual(result, "")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=0 单条
    def test_changes0_single(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.stone", "Stone", "石头", "1.20.4", "1.21.1", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("stone")
            self.assertIn("石头", result)
            self.assertIn("1.20.4-1.21.1", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=0 多条
    def test_changes0_multiple(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.a", "Apple", "苹果", "1.20.0", "1.21.0")
            _insert(conn, "key.b", "Banana", "香蕉", "1.20.0", "1.21.0")
            _insert(conn, "key.c", "Cherry", "樱桃", "1.20.0", "1.21.0")
            conn.commit()
            store.load()
            result = store.lookup("apple")
            self.assertIn("苹果", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=0 通过单一术语匹配
    def test_changes0_single_term(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test stone block", "测试石头", "1.20.0", "1.21.0")
            conn.commit()
            store.load()
            result = store.lookup("stone")
            self.assertIn("测试石头", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=1 二次查询全量
    def test_changes1_full_history(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.open_realm", "Open realm", "打开Realm", "1.16.5", "1.18.2", changes=1)
            _insert(conn, "key.open_realm", "Open realm", "已打开Realm", "1.19.4", "1.20.1", changes=1)
            _insert(conn, "key.open_realm", "Open realm", "Reopen Realm", "26.1.2", "26.1.2", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("open realm")
            self.assertIn("打开Realm", result)
            self.assertIn("已打开Realm", result)
            self.assertIn("Reopen Realm", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=1 版本敏感 header
    def test_changes1_header(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "测试A", "1.16.0", "1.18.0", changes=1)
            _insert(conn, "key.test", "Test", "测试B", "1.19.0", "1.21.0", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("test")
            self.assertIn("版本敏感译名", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # changes=0 也有 header
    def test_changes0_header(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.stone", "Stone", "石头", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("stone")
            self.assertIn("原版词典", result)
            self.assertNotIn("版本敏感译名", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # primary/sub 排序：target_version 匹配行优先
    def test_primary_sub_target_version(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "旧版", "1.16.5", "1.18.2", changes=1)
            _insert(conn, "key.test", "Test", "新版", "1.19.4", "1.21.1", changes=1)
            _insert(conn, "key.test", "Test", "最新", "26.1.2", "26.1.2", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("test", target_version="1.20.1")
            lines = [l for l in result.split("\n") if l.strip()]
            self.assertGreater(len(lines), 1)
            primary_line = lines[2]  # lines[0]=header, lines[1]=word header
            self.assertIn("新版", primary_line)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # primary/sub 排序：无 target 时最新优先
    def test_primary_sub_no_target(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "旧版", "1.16.5", "1.18.2", changes=1)
            _insert(conn, "key.test", "Test", "中版", "1.19.0", "1.20.0", changes=1)
            _insert(conn, "key.test", "Test", "最新", "26.1.2", "26.1.2", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("test")
            lines = [l for l in result.split("\n") if l.strip()]
            self.assertGreater(len(lines), 1)
            primary_line = lines[2]  # lines[0]=header, lines[1]=word header
            self.assertIn("最新", primary_line)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # sub 行前缀 "- "
    def test_sub_prefix(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "第一版", "1.16.0", "1.18.0", changes=1)
            _insert(conn, "key.test", "Test", "第二版", "1.19.0", "1.21.0", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("test")
            sub_lines = [l for l in result.split("\n") if l.startswith("- ")]
            self.assertEqual(len(sub_lines), 1)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 停用词过滤
    def test_stop_words_filtered(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.the", "The", "定冠词", "1.20.0", "1.21.0")
            conn.commit()
            store.load()
            result = store.lookup("the")
            self.assertEqual(result, "")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 格式占位符过滤：%d, %s 等不作为搜索词
    def test_format_specifier_filtered(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Test", "测试", "1.20.0", "1.21.0")
            conn.commit()
            store.load()
            result = store.lookup("%d")
            self.assertEqual(result, "")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 标点剥离：Animals. 只去掉句点，搜到 animals 相关条目
    def test_punctuation_stripped_word_in_multiword(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.animal", "Animals", "动物", "1.20.0", "1.21.0")
            conn.commit()
            store.load()
            result = store.lookup("Animals.")
            self.assertIn("动物", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 多词搜索：按匹配单词分组，每个词内 changes=0 + changes=1 混合
    def test_changes_mixed_normal_both_ends(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.short", "Stone", "石头", "1.20.0", "1.21.0", changes=0)
            _insert(conn, "key.long", "Polished Deepslate Brick", "磨制深板岩砖", "1.20.0", "1.21.0", changes=0)
            _insert(conn, "key.sens", "Sensitive A", "敏感A", "1.19.0", "1.20.0", changes=1)
            _insert(conn, "key.sens", "Sensitive B", "敏感B", "1.20.1", "1.21.0", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("stone polished sensitive")
            self.assertIn("Stone：", result)
            self.assertIn("Polished：", result)
            self.assertIn("Sensitive：", result)
            self.assertIn("磨制深板岩砖", result)
            self.assertIn("石头", result)
            self.assertIn("敏感A", result)
            self.assertIn("敏感B", result)
            stone_count = sum(1 for l in result.split("\n") if "石头" in l)
            self.assertEqual(stone_count, 1, "Stone 不应重复出现")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 只有一个 normal 条目时，不作为 shortest 重复出现
    def test_changes_mixed_single_normal(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.only", "Stone", "石头", "1.20.0", "1.21.0", changes=0)
            _insert(conn, "key.sens", "Sensitive A", "敏感A", "1.19.0", "1.20.0", changes=1)
            _insert(conn, "key.sens", "Sensitive B", "敏感B", "1.20.1", "1.21.0", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("stone sensitive")
            self.assertIn("Stone：", result)
            self.assertIn("Sensitive：", result)
            self.assertIn("石头", result)
            self.assertIn("敏感A", result)
            self.assertIn("敏感B", result)
            stone_count = sum(1 for l in result.split("\n") if "石头" in l)
            self.assertEqual(stone_count, 1, "唯一的 normal 不应重复出现")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 超 6 词退化模糊查询 → 无单词标题
    def test_long_text_fuzzy_fallback(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "Very long search query copper ore diamond", "测试长句", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("this is a very long search query about copper ore diamond")
            self.assertIn("测试长句", result)
            self.assertNotIn("Very：", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 含 desc 退化模糊查询
    def test_desc_triggers_fuzzy(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.test", "desc test", "描述测试", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("this is a desc test")
            self.assertIn("描述测试", result)
            self.assertNotIn("Desc：", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # block 强制逐词分组（即使超 6 词也不退化；block 虽在停用词表仍作为策略依据）
    def test_block_item_force_per_word(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.thing", "Thing", "东西", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("this block thing with a very long search text for test")
            self.assertIn("Thing：", result, "block→per-word mode, should have word headers")
            self.assertIn("东西", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # close 方法
    def test_close(self):
        path, conn, store = self._make_store_and_conn()
        store.load()
        store.close()
        self.assertIsNone(store._conn)
        conn.close()
        Path(path).unlink(missing_ok=True)

    # 长文本退化查询 — 相似度过低应被过滤
    def test_similarity_filter_irrelevant(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.irrelevant", "A stone", "一块石头", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("this is a very long and specific query about stone mining enchantment")
            self.assertEqual(result, "", "共享单词但文本不相关，低相似度应被过滤")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 长文本退化查询 — 相似度足够应保留
    def test_similarity_filter_relevant(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.relevant", "Rare earth mineral mining deep stone", "稀土矿物开采深石", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("rare earth mineral mining deep stone with various ores")
            self.assertIn("稀土矿物开采深石", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # desc 触发退化但词数未超阈值 → 不应用相似度过滤
    def test_similarity_not_applied_to_short_desc(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.desc", "Stone desc", "石头描述", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("stone desc")
            self.assertIn("石头描述", result)
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # FTS5 仅搜索 en_us 列 → key 中含词但 en_us 不含的条目不应出现
    def test_key_only_match_excluded(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "subtitles.entity.bee.gulping", "Gulping", "吞咽", "1.16.5", "26.1.2", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("bottle bee")
            self.assertNotIn("吞咽", result, "key 含 bee 但 en_us 不含 bottle，不应匹配")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 跨词去重：同一 key 不在多个词组重复出现
    def test_cross_word_dedup(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.shared", "Campfire bottle honey", "营火蜂蜜瓶", "1.20.0", "1.21.0", changes=0)
            _insert(conn, "key.bee", "Bee", "蜜蜂", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            result = store.lookup("bottle bee campfire honey")
            self.assertIn("营火蜂蜜瓶", result)
            campfire_count = result.count("营火蜂蜜瓶")
            self.assertEqual(campfire_count, 1, "同一 key 不应在多词组中重复出现")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 模拟用户场景：蜜蜂玻璃瓶收集蜂蜜
    def test_bee_bottle_honey_scenario(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.bee", "Bee", "蜜蜂", "1.16.5", "26.1.2", changes=0)
            _insert(conn, "key.glass", "Glass", "玻璃", "1.16.5", "26.1.2", changes=0)
            _insert(conn, "key.honey_bottle", "Honey Bottle", "蜂蜜瓶", "1.16.5", "26.1.2", changes=0)
            _insert(conn, "key.harvest_honey", "Use a Campfire to collect Honey from a Beehive using a Glass Bottle without aggravating the Bees",
                    "利用营火在不惊动蜜蜂的情况下从蜂巢收集蜂蜜", "1.20.1", "26.1.2", changes=1)
            _insert(conn, "key.harvest_honey", "Use a Campfire to collect Honey from a Beehive using a Bottle without aggravating the Bees",
                    "利用营火在不惊动蜜蜂的情况下从蜂巢收集蜂蜜", "1.19.4", "1.19.4", changes=1)
            conn.commit()
            store.load()
            result = store.lookup("Use a glass bottle on a Bee to collect honey")
            self.assertIn("蜜蜂", result, "应出现 Bee → 蜜蜂")
            self.assertIn("玻璃", result, "应出现 Glass → 玻璃")
            self.assertIn("利用营火", result, "应出现营火收集蜂蜜的原版参考")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 词形归并：原词 < 3 个 unique key 时 fallback 到词根
    def test_lemma_fallback_kills_to_kill(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.player_kills", "Player Kills", "玩家击杀数", "1.12.2", "1.12.2", changes=0)
            _insert(conn, "key.player_kills", "Player Kills", "玩家击杀数", "1.16.5", "26.1.2", changes=0)
            _insert(conn, "key.kill_entity", "Kill a Creeper", "击杀一只苦力怕", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            store._lemma_map = {"kills": "kill"}
            result = store.lookup("kills")
            self.assertIn("玩家击杀数", result)
            self.assertIn("击杀一只苦力怕", result, "词形归并应找到 kill 的结果")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)

    # 词形归并：原词足够时不触发 fallback
    def test_lemma_fallback_no_trigger_when_enough(self):
        path, conn, store = self._make_store_and_conn()
        try:
            _insert(conn, "key.a", "Stone A", "石头A", "1.20.0", "1.21.0", changes=0)
            _insert(conn, "key.b", "Stone B", "石头B", "1.20.0", "1.21.0", changes=0)
            _insert(conn, "key.c", "Stone C", "石头C", "1.20.0", "1.21.0", changes=0)
            _insert(conn, "key.stones_variant", "Stones", "石块", "1.20.0", "1.21.0", changes=0)
            conn.commit()
            store.load()
            store._lemma_map = {"stones": "stone"}  # "stone" would match even more
            result = store.lookup("stone")  # already ≥3 unique keys, no fallback needed
            self.assertIn("石头A", result)
            self.assertIn("石头B", result)
            self.assertIn("石头C", result)
            self.assertNotIn("石块", result, "原词已足够，不应触发词形归并")
        finally:
            store.close()
            conn.close()
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
