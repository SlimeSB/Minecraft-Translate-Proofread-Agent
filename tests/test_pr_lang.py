"""测试 PR 审校 — JSON 语言文件对齐。"""
import unittest

from src.tools.pr._lang import match, group_mod_files, align


class TestMatchPathRegex(unittest.TestCase):

    def test_old_structure(self):
        result = match("projects/assets/appliedenergistics2/1.18/appliedenergistics2/lang/en_us.json")
        self.assertEqual(result["curseforge_id"], "appliedenergistics2")
        self.assertEqual(result["version"], "1.18")
        self.assertEqual(result["slug"], "appliedenergistics2")
        self.assertEqual(result["lang"], "en_us")

    def test_old_structure_zh(self):
        result = match("projects/assets/create/1.16/create/lang/zh_cn.json")
        self.assertEqual(result["curseforge_id"], "create")
        self.assertEqual(result["lang"], "zh_cn")

    def test_new_structure(self):
        result = match("projects/1.20/assets/mekanism/mekanism/lang/en_us.json")
        self.assertEqual(result["curseforge_id"], "mekanism")
        self.assertEqual(result["version"], "1.20")
        self.assertEqual(result["slug"], "mekanism")
        self.assertEqual(result["lang"], "en_us")

    def test_new_structure_zh(self):
        result = match("projects/1.19/assets/botania/botania/lang/zh_cn.json")
        self.assertEqual(result["curseforge_id"], "botania")
        self.assertEqual(result["lang"], "zh_cn")

    def test_non_lang_file(self):
        self.assertIsNone(match("projects/assets/mod/1.18/mod/lang/readme.txt"))
        self.assertIsNone(match("src/main/java/Foo.java"))

    def test_guide_me_not_matched(self):
        self.assertIsNone(match("projects/assets/ae2/1.18/ae2/ae2guide/index.md"))


class TestGroupModFiles(unittest.TestCase):

    def test_single_mod_modified(self):
        files = [
            {"filename": "projects/assets/testmod/1.18/testmod/lang/en_us.json", "status": "modified"},
            {"filename": "projects/assets/testmod/1.18/testmod/lang/zh_cn.json", "status": "modified"},
        ]
        mods = group_mod_files(files)
        self.assertEqual(len(mods), 1)
        key = "1.18/testmod/testmod"
        self.assertIn(key, mods)
        self.assertIsNotNone(mods[key]["en_head"])
        self.assertIsNotNone(mods[key]["zh_head"])

    def test_multi_mod(self):
        files = [
            {"filename": "projects/assets/mod_a/1.18/mod_a/lang/en_us.json", "status": "modified"},
            {"filename": "projects/assets/mod_a/1.18/mod_a/lang/zh_cn.json", "status": "modified"},
            {"filename": "projects/assets/mod_b/1.16/mod_b/lang/en_us.json", "status": "modified"},
            {"filename": "projects/assets/mod_b/1.16/mod_b/lang/zh_cn.json", "status": "modified"},
        ]
        mods = group_mod_files(files)
        self.assertEqual(len(mods), 2)

    def test_zh_missing_infers_from_en(self):
        files = [
            {"filename": "projects/assets/testmod/1.18/testmod/lang/en_us.json", "status": "modified"},
        ]
        mods = group_mod_files(files)
        key = "1.18/testmod/testmod"
        self.assertIn(key, mods)
        self.assertIn("zh_cn.json", mods[key]["zh_head"])

    def test_removed_file_becomes_base_only(self):
        files = [
            {"filename": "projects/assets/testmod/1.18/testmod/lang/en_us.json", "status": "removed"},
        ]
        mods = group_mod_files(files)
        key = "1.18/testmod/testmod"
        self.assertEqual(mods[key]["en_base"],
                         "projects/assets/testmod/1.18/testmod/lang/en_us.json")
        self.assertIsNone(mods[key]["en_head"])

    def test_new_structure_grouping(self):
        files = [
            {"filename": "projects/1.20/assets/tinkers/tconstruct/lang/en_us.json", "status": "modified"},
            {"filename": "projects/1.20/assets/tinkers/tconstruct/lang/zh_cn.json", "status": "modified"},
        ]
        mods = group_mod_files(files)
        self.assertEqual(len(mods), 1)
        key = "1.20/tinkers/tconstruct"
        self.assertIn(key, mods)


class TestAlign(unittest.TestCase):

    def test_both_changed(self):
        old_en = {"item.sword": "Iron Sword", "item.pick": "Iron Pickaxe"}
        new_en = {"item.sword": "Steel Sword", "item.pick": "Iron Pickaxe"}
        old_zh = {"item.sword": "铁剑", "item.pick": "铁镐"}
        new_zh = {"item.sword": "钢剑", "item.pick": "铁镐"}
        entries, warnings = align(old_en, new_en, old_zh, new_zh)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "item.sword")
        self.assertEqual(entries[0]["review_type"], "normal")
        self.assertEqual(entries[0]["old_en"], "Iron Sword")
        self.assertEqual(entries[0]["old_zh"], "铁剑")

    def test_en_changed_zh_unchanged(self):
        old_en = {"item.food": "Apple"}
        new_en = {"item.food": "Golden Apple"}
        old_zh = {"item.food": "苹果"}
        new_zh = {"item.food": "苹果"}
        entries, warnings = align(old_en, new_en, old_zh, new_zh)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["review_type"], "en_changed_zh_unchanged")
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["type"], "en_changed_zh_unchanged")

    def test_zh_only_change(self):
        old_en = {"item.food": "Bread"}
        new_en = {"item.food": "Bread"}
        old_zh = {"item.food": "面包"}
        new_zh = {"item.food": "小麦面包"}
        entries, warnings = align(old_en, new_en, old_zh, new_zh)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["review_type"], "zh_only_change")

    def test_no_change_skipped(self):
        old_en = {"key.a": "A"}
        new_en = {"key.a": "A"}
        old_zh = {"key.a": "甲"}
        new_zh = {"key.a": "甲"}
        entries, _ = align(old_en, new_en, old_zh, new_zh)
        self.assertEqual(len(entries), 0)

    def test_new_key_added(self):
        old_en = {}
        new_en = {"key.new": "New"}
        old_zh = {}
        new_zh = {"key.new": "新"}
        entries, _ = align(old_en, new_en, old_zh, new_zh)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["review_type"], "normal")
        self.assertEqual(entries[0]["old_en"], "")
        self.assertEqual(entries[0]["old_zh"], "")

    def test_key_removed_becomes_empty(self):
        old_en = {"key.old": "Old"}
        new_en = {}
        old_zh = {"key.old": "旧"}
        new_zh = {}
        entries, _ = align(old_en, new_en, old_zh, new_zh)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["en"], "")
        self.assertEqual(entries[0]["zh"], "")

    def test_entry_has_format_json(self):
        old_en = {"item.x": "X"}
        new_en = {"item.x": "X2"}
        old_zh = {"item.x": "某"}
        new_zh = {"item.x": "某2"}
        entries, _ = align(old_en, new_en, old_zh, new_zh)
        self.assertEqual(entries[0]["format"], "json")


if __name__ == "__main__":
    unittest.main()
