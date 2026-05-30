"""测试 PR 审校 — 手册/文档对齐（启发式 + Agent 兜底）。"""
import unittest

from src.tools.pr._guideme import align


class TestManualAlignMatch(unittest.TestCase):

    def test_non_doc_file_skipped(self):
        files = [{"filename": "projects/assets/mod/1.18/mod/lang/en_us.json", "status": "modified"}]
        def mock_get(url, _token):
            return "{}"
        entries, _ = align(files, "https://base", "https://head", mock_get, "fake-token")
        self.assertEqual(len(entries), 0)

    def test_not_md_or_json_skipped(self):
        files = [{"filename": "projects/assets/mod/1.18/mod/ae2guide/index.txt", "status": "modified"}]
        def mock_get(url, _token):
            return "text"
        entries, _ = align(files, "https://base", "https://head", mock_get, "fake-token")
        self.assertEqual(len(entries), 0)


class TestManualAlign(unittest.TestCase):

    BASE = "https://raw.base"
    HEAD = "https://raw.head"
    FP_EN = "projects/assets/mod/1.18/mod/ae2guide/index.md"
    FP_ZH = "projects/assets/mod/1.18/mod/ae2guide/_zh_cn/index.md"

    def _make_url(self, base, fp):
        return f"{base}/{fp}"

    def test_both_found_produces_entry(self):
        en_base_url = self._make_url(self.BASE, self.FP_EN)
        zh_base_url = self._make_url(self.BASE, self.FP_ZH)
        en_head_url = self._make_url(self.HEAD, self.FP_EN)
        zh_head_url = self._make_url(self.HEAD, self.FP_ZH)

        data = {
            en_base_url: "# EN Old",
            zh_base_url: "# ZH Old",
            en_head_url: "# EN Content",
            zh_head_url: "# ZH 内容",
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
        self.assertEqual(entries[0]["format"], "manual")
        self.assertEqual(entries[0]["review_type"], "modified")
        self.assertEqual(entries[0]["old_en"], "# EN Old")
        self.assertEqual(entries[0]["old_zh"], "# ZH Old")
        self.assertEqual(entries[0]["file_path"], self.FP_EN)

    def test_nested_path(self):
        fp_en = "projects/assets/mod/1.18/mod/ae2guide/sub/dir/page.md"
        fp_zh = "projects/assets/mod/1.18/mod/ae2guide/_zh_cn/sub/dir/page.md"
        en_base_url = self._make_url(self.BASE, fp_en)
        zh_base_url = self._make_url(self.BASE, fp_zh)
        en_head_url = self._make_url(self.HEAD, fp_en)
        zh_head_url = self._make_url(self.HEAD, fp_zh)

        data = {
            en_base_url: "EN Old",
            zh_base_url: "ZH Old",
            en_head_url: "EN",
            zh_head_url: "ZH",
        }

        def mock_get(url, _token):
            return data[url]

        files = [
            {"filename": fp_en, "status": "modified"},
            {"filename": fp_zh, "status": "modified"},
        ]
        entries, _ = align(files, self.BASE, self.HEAD, mock_get, "fake-token")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "ae2guide:sub/dir/page.md")

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
