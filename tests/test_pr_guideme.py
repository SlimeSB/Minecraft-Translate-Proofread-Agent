"""测试 PR 审校 — GuideME 文档对齐。"""
import unittest

from src.tools.pr._guideme import match, align


class TestGuidemeMatch(unittest.TestCase):

    def test_old_structure_en(self):
        result = match("projects/assets/ae2/1.18/ae2/ae2guide/index.md")
        self.assertIsNotNone(result)
        self.assertEqual(result["curseforge_id"], "ae2")
        self.assertEqual(result["version"], "1.18")
        self.assertEqual(result["slug"], "ae2")
        self.assertFalse(result["is_zh"])
        self.assertEqual(result["rel_path"], "index.md")

    def test_old_structure_zh(self):
        result = match("projects/assets/ae2/1.18/ae2/ae2guide/_zh_cn/index.md")
        self.assertIsNotNone(result)
        self.assertTrue(result["is_zh"])
        self.assertEqual(result["rel_path"], "index.md")

    def test_new_structure_en(self):
        result = match("projects/1.20/assets/ars_nouveau/ars_nouveau/ae2guide/getting_started.md")
        self.assertIsNotNone(result)
        self.assertEqual(result["curseforge_id"], "ars_nouveau")
        self.assertEqual(result["version"], "1.20")
        self.assertEqual(result["slug"], "ars_nouveau")
        self.assertFalse(result["is_zh"])
        self.assertEqual(result["rel_path"], "getting_started.md")

    def test_new_structure_zh(self):
        result = match("projects/1.20/assets/ars_nouveau/ars_nouveau/ae2guide/_zh_cn/getting_started.md")
        self.assertIsNotNone(result)
        self.assertTrue(result["is_zh"])

    def test_nested_path(self):
        result = match("projects/assets/mod/1.18/mod/ae2guide/sub/dir/page.md")
        self.assertIsNotNone(result)
        self.assertEqual(result["rel_path"], "sub/dir/page.md")

    def test_non_guideme_file(self):
        self.assertIsNone(match("projects/assets/mod/1.18/mod/lang/en_us.json"))
        self.assertIsNone(match("src/main/java/Foo.java"))

    def test_not_md_extension(self):
        self.assertIsNone(match("projects/assets/mod/1.18/mod/ae2guide/index.txt"))


class TestGuidemeAlign(unittest.TestCase):

    BASE = "https://raw.base"
    HEAD = "https://raw.head"
    FP_EN = "projects/assets/mod/1.18/mod/ae2guide/index.md"
    FP_ZH = "projects/assets/mod/1.18/mod/ae2guide/_zh_cn/index.md"

    def _make_url(self, base, fp):
        return f"{base}/{fp}"

    def test_both_changed_produces_entry(self):
        en_url = self._make_url(self.BASE, self.FP_EN)
        zh_url = self._make_url(self.BASE, self.FP_ZH)
        en_head_url = self._make_url(self.HEAD, self.FP_EN)
        zh_head_url = self._make_url(self.HEAD, self.FP_ZH)

        data = {
            en_url: "# EN Old\nContent",
            zh_url: "# ZH Old\n内容",
            en_head_url: "# EN Updated\nNew Content",
            zh_head_url: "# ZH Updated\n新内容",
        }

        def mock_get(url, _token):
            return data[url]

        files = [
            {"filename": self.FP_EN, "status": "modified"},
            {"filename": self.FP_ZH, "status": "modified"},
        ]
        entries, _ = align(files, self.BASE, self.HEAD, mock_get, "fake-token")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "ae2guide:index.md")
        self.assertEqual(entries[0]["format"], "guideme")
        self.assertEqual(entries[0]["review_type"], "normal")
        self.assertEqual(entries[0]["version"], "1.18")
        self.assertEqual(entries[0]["file_path"], self.FP_EN)

    def test_en_changed_zh_unchanged_produces_warning(self):
        en_url = self._make_url(self.BASE, self.FP_EN)
        zh_url = self._make_url(self.BASE, self.FP_ZH)
        en_head_url = self._make_url(self.HEAD, self.FP_EN)
        zh_head_url = self._make_url(self.HEAD, self.FP_ZH)

        data = {
            en_url: "# Old EN",
            zh_url: "# Same ZH",
            en_head_url: "# New EN",
            zh_head_url: "# Same ZH",
        }

        def mock_get(url, _token):
            return data[url]

        files = [
            {"filename": self.FP_EN, "status": "modified"},
        ]
        entries, warnings = align(files, self.BASE, self.HEAD, mock_get, "fake-token")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["review_type"], "en_changed_zh_unchanged")
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["type"], "en_changed_zh_unchanged")

    def test_zh_only_change(self):
        en_url = self._make_url(self.BASE, self.FP_EN)
        zh_url = self._make_url(self.BASE, self.FP_ZH)
        en_head_url = self._make_url(self.HEAD, self.FP_EN)
        zh_head_url = self._make_url(self.HEAD, self.FP_ZH)

        data = {
            en_url: "Same EN",
            zh_url: "Old ZH",
            en_head_url: "Same EN",
            zh_head_url: "New ZH",
        }

        def mock_get(url, _token):
            return data[url]

        files = [
            {"filename": self.FP_EN, "status": "modified"},
            {"filename": self.FP_ZH, "status": "added"},
        ]
        entries, _ = align(files, self.BASE, self.HEAD, mock_get, "fake-token")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["review_type"], "zh_only_change")

    def test_no_change_skipped(self):
        en_url = self._make_url(self.BASE, self.FP_EN)
        zh_url = self._make_url(self.BASE, self.FP_ZH)
        en_head_url = self._make_url(self.HEAD, self.FP_EN)
        zh_head_url = self._make_url(self.HEAD, self.FP_ZH)

        data = {
            en_url: "Same",
            zh_url: "相同",
            en_head_url: "Same",
            zh_head_url: "相同",
        }

        def mock_get(url, _token):
            return data[url]

        files = [
            {"filename": self.FP_EN, "status": "modified"},
            {"filename": self.FP_ZH, "status": "modified"},
        ]
        entries, _ = align(files, self.BASE, self.HEAD, mock_get, "fake-token")
        self.assertEqual(len(entries), 0)

    def test_fetch_error_produces_warning_not_crash(self):
        def error_get(url, token):
            if "_zh_cn/" in url:
                raise RuntimeError("Failed to fetch zh_cn")
            return "EN content"

        files = [
            {"filename": self.FP_EN, "status": "modified"},
            {"filename": self.FP_ZH, "status": "modified"},
        ]
        entries, warnings = align(files, self.BASE, self.HEAD, error_get, "fake-token")
        self.assertEqual(len(entries), 0)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["type"], "fetch_error")


if __name__ == "__main__":
    unittest.main()
