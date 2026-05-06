"""测试 FormatChecker 的关键检查函数。"""
import unittest

from src.checkers.format_checker import FormatChecker, RE_PRINTF, RE_POSITIONAL_PRINTF


class TestPlaceholderIntegrity(unittest.TestCase):
    def setUp(self):
        self.checker = FormatChecker()

    def _check(self, en: str, zh: str, key: str = "test.key") -> dict | None:
        return self.checker._check_placeholder_integrity(key, en, zh)

    def test_pass_basic_printf(self):
        """基本的 %d, %s 一致应 PASS。"""
        self.assertIsNone(self._check("HP: %d", "血量: %d"))
        self.assertIsNone(self._check("Name: %s", "名称: %s"))

    def test_fail_missing_placeholder(self):
        """译文缺少占位符应 FAIL。"""
        result = self._check("HP: %d / %d", "血量: %d")
        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "❌ FAIL")
        self.assertIn("占位符不一致", result["reason"])

    def test_fail_extra_placeholder(self):
        """译文多余占位符应 FAIL。"""
        result = self._check("HP: %d", "血量: %d / %d")
        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "❌ FAIL")

    def test_positional_printf_normalized(self):
        """位置占位符 %1$s 归一化后应与 %s 等价。"""
        self.assertIsNone(self._check("Player %1$s killed %2$s", "%2$s 杀了 %1$s"))

    def test_positional_printf_missing(self):
        """位置占位符缺失应 FAIL。"""
        result = self._check("Player %1$s killed %2$s", "%2$s 杀了")
        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "❌ FAIL")
        self.assertIn("缺失占位符", result["reason"])

    def test_pass_percent_var(self):
        """%msg% 风格变量一致应 PASS。"""
        self.assertIsNone(self._check("Left click to %action%", "左键以 %action%"))

    def test_fail_percent_var_missing(self):
        """缺失 %msg% 变量应 FAIL。"""
        result = self._check("Left click to %action%", "左键以")
        self.assertIsNotNone(result)
        self.assertIn("缺失变量", result["reason"])

    def test_pass_brace_var(self):
        """{0}, {1} 风格一致应 PASS。"""
        self.assertIsNone(self._check("{0} of {1}", "第 {0} / {1}"))

    def test_fail_brace_var(self):
        """缺失 {0} 变量应 FAIL。"""
        result = self._check("{0} of {1}", "第 {0}")
        self.assertIsNotNone(result)
        self.assertIn("缺失变量", result["reason"])

    def test_mixed_placeholder_types(self):
        """混合类型占位符应全部检查。"""
        self.assertIsNone(self._check("%d items, %s, %msg%", "%d 个物品, %s, %msg%"))

    def test_no_placeholders(self):
        """无占位符文本应 PASS。"""
        self.assertIsNone(self._check("Hello World", "你好世界"))


class TestSpecialTags(unittest.TestCase):
    def setUp(self):
        self.checker = FormatChecker()

    def _check(self, en: str, zh: str, key: str = "test.key") -> dict | None:
        return self.checker._check_special_tags(key, en, zh)

    def test_pass_mc_color(self):
        """§颜色码一致应 PASS。"""
        self.assertIsNone(self._check("§6Gold", "§6金"))

    def test_fail_mc_color_missing(self):
        """缺失 § 颜色码应 FAIL。"""
        result = self._check("§6Gold §cRed", "§6金")
        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "❌ FAIL")

    def test_pass_br_tag(self):
        """<br> 数量一致应 PASS。"""
        self.assertIsNone(self._check("Line1<br>Line2<br>", "第一行<br>第二行<br>"))

    def test_fail_br_count(self):
        """<br> 数量不一致应 FAIL。"""
        result = self._check("Line1<br>Line2<br>", "第一行第二行")
        self.assertIsNotNone(result)
        self.assertIn("<br>", result["reason"])

    def test_pass_newline(self):
        """\\n 数量一致应 PASS。"""
        self.assertIsNone(self._check("A\\nB", "甲\\n乙"))

    def test_fail_newline_count(self):
        """\\n 数量不一致应 FAIL。"""
        result = self._check("A\\nB\\nC", "甲\\n乙")
        self.assertIsNotNone(result)
        self.assertIn("换行符", result["reason"])

    def test_pass_html_tags(self):
        """HTML 标签一致应 PASS。"""
        self.assertIsNone(self._check("<red>Text</red>", "<red>文本</red>"))

    def test_fail_html_tags(self):
        """HTML 标签丢失应 FAIL。"""
        result = self._check("<red>Text</red>", "文本")
        self.assertIsNotNone(result)
        self.assertIn("HTML", result["reason"])

    def test_pass_no_tags(self):
        """无特殊标签文本应 PASS。"""
        self.assertIsNone(self._check("Hello", "你好"))


class TestEmptyTranslation(unittest.TestCase):
    def setUp(self):
        self.checker = FormatChecker()

    def _check(self, en: str, zh: str, key: str = "test.key") -> dict | None:
        return self.checker._check_empty_translation(key, en, zh)

    def test_fail_zh_equals_en_not_code(self):
        """zh == en 且非代码应 FAIL。"""
        result = self._check("Hello World", "Hello World")
        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "❌ FAIL")

    def test_pass_code_constant(self):
        """全大写常量 zh==en 应 PASS。"""
        self.assertIsNone(self._check("GUI_TITLE", "GUI_TITLE"))

    def test_pass_different_text(self):
        """不同文本应 PASS。"""
        self.assertIsNone(self._check("Hello", "你好"))


class TestEnergyUnits(unittest.TestCase):
    def setUp(self):
        self.checker = FormatChecker()

    def _check(self, en: str, zh: str) -> dict | None:
        return self.checker._check_energy_units("test.key", en, zh)

    def test_pass_units_preserved(self):
        """能量单位保留应 PASS。"""
        self.assertIsNone(self._check("1000 FE", "1000 FE"))
        self.assertIsNone(self._check("500 RF/t", "500 RF/t"))

    def test_fail_units_translated(self):
        """能量单位被翻译应 FAIL。"""
        result = self._check("1000 FE", "1000 能量")
        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "❌ FAIL")

    def test_no_units(self):
        """无能量单位应 PASS。"""
        self.assertIsNone(self._check("Hello", "你好"))


class TestEllipsis(unittest.TestCase):
    def setUp(self):
        self.checker = FormatChecker()

    def _check(self, en: str, zh: str) -> dict | None:
        return self.checker._check_ellipsis("test.key", en, zh)

    def test_fail_three_dots(self):
        """... 应被标记。"""
        result = self._check("Loading...", "加载中...")
        self.assertIsNotNone(result)
        self.assertIn("省略号", result["reason"])

    def test_pass_correct_ellipsis(self):
        """正确的省略号应 PASS。"""
        self.assertIsNone(self._check("Loading...", "加载中⋯⋯"))


class TestRegexPatterns(unittest.TestCase):
    def test_re_printf_basic(self):
        """RE_PRINTF 匹配基本模式。"""
        matches = RE_PRINTF.findall("HP: %d / %s")
        self.assertEqual(matches, ["%d", "%s"])

    def test_re_printf_positional(self):
        """RE_POSITIONAL_PRINTF 匹配位置参数。"""
        matches = RE_POSITIONAL_PRINTF.findall("%1$s killed %2$s")
        self.assertEqual(matches, ["%1$s", "%2$s"])

    def test_re_printf_not_match_positional(self):
        """RE_PRINTF 不匹配位置参数（由 RE_POSITIONAL_PRINTF 单独处理）。"""
        matches = RE_PRINTF.findall("%1$s killed %2$s")
        self.assertEqual(matches, [])

    def test_re_printf_formatted(self):
        """RE_PRINTF 匹配格式化参数。"""
        matches = RE_PRINTF.findall("%.2f %+d")
        self.assertEqual(matches, ["%.2f", "%+d"])


if __name__ == "__main__":
    unittest.main()
