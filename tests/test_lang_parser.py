"""测试 .lang 文件解析器。"""
import unittest

from src.tools.lang_parser import load_lang_text


class TestLangParser(unittest.TestCase):
    def test_basic_key_value(self):
        """基本 key=value 解析。"""
        d, w = load_lang_text("item.apple.name=Apple")
        self.assertEqual(d, {"item.apple.name": "Apple"})
        self.assertEqual(w, [])

    def test_colon_separator(self):
        """冒号分隔符。"""
        d, _ = load_lang_text("item.apple.name:Apple")
        self.assertEqual(d, {"item.apple.name": "Apple"})

    def test_comment_lines(self):
        """注释行被忽略。"""
        d, _ = load_lang_text("# comment\nitem.apple.name=Apple\n! also comment")
        self.assertEqual(d, {"item.apple.name": "Apple"})

    def test_skip_empty(self):
        """空行被跳过。"""
        d, _ = load_lang_text("\n\nitem.apple.name=Apple\n\n  \n")
        self.assertEqual(d, {"item.apple.name": "Apple"})

    def test_duplicate_key(self):
        """重复 key 报警。"""
        d, w = load_lang_text("a=1\na=2")
        self.assertEqual(d, {"a": "2"})
        self.assertTrue(any("重复key" in x for x in w))

    def test_equals_in_value(self):
        """值中包含 = 的文本只按第一个 = 拆分。"""
        d, _ = load_lang_text("a=b=c")
        self.assertEqual(d, {"a": "b=c"})

    def test_colon_in_value(self):
        """值中包含 : 的文本只按分隔符拆分。"""
        d, _ = load_lang_text("time.format=HH:MM:SS")
        self.assertEqual(d, {"time.format": "HH:MM:SS"})

    def test_line_continuation(self):
        """行尾 \\ 续行。"""
        d, _ = load_lang_text("lore=This is a very\\\nlong description")
        self.assertEqual(d, {"lore": "This is a verylong description"})

    def test_parse_escapes(self):
        """#PARSE_ESCAPE 模式处理转义。"""
        text = "#PARSE_ESCAPE\nkey\\=with\\=equals=value"
        d, _ = load_lang_text(text)
        self.assertEqual(d, {"key=with=equals": "value"})

    def test_unicode_escape(self):
        """Unicode 转义 \\uXXXX。"""
        text = "#PARSE_ESCAPE\nkey=\\u4e2d\\u6587"
        d, _ = load_lang_text(text)
        # \u4e2d = 中, \u6587 = 文
        self.assertIn("中", d["key"])

    def test_empty_input(self):
        """空输入。"""
        d, w = load_lang_text("")
        self.assertEqual(d, {})
        self.assertEqual(w, [])


if __name__ == "__main__":
    unittest.main()
