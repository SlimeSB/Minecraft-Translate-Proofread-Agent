""".lang 文件解析器：将 key=value 格式的语言文件加载为 dict。

支持: key=value, key:value, #注释, !注释, #PARSE_ESCAPE, 行尾\\续行

用法:
    from lang_parser import load_lang, load_lang_text
"""
import re


def load_lang(path: str) -> tuple[dict[str, str], list[str]]:
    """加载 .lang 文件，返回 (data_dict, warnings)。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        return load_lang_text(f.read())


def load_lang_text(text: str) -> tuple[dict[str, str], list[str]]:
    """从文本字符串解析 .lang 内容。"""
    lines = text.splitlines(keepends=False)
    data: dict[str, str] = {}
    warnings: list[str] = []
    parse_escapes = False

    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n\r")
        i += 1

        if line.strip().upper() == "#PARSE_ESCAPE":
            parse_escapes = True
            continue
        if line.lstrip().startswith("#") or line.lstrip().startswith("!"):
            continue
        if not line.strip():
            continue

        # 行尾 \\ 续行：移除 \\ 并连接下一行
        while line.endswith("\\") and i < len(lines):
            line = line[:-1] + lines[i].rstrip("\n\r")
            i += 1

        _parse_line(line, parse_escapes, data, warnings)

    return data, warnings


_SPLIT_RE = re.compile(r"([=:])")


def _parse_line(
    line: str,
    parse_escapes: bool,
    data: dict[str, str],
    warnings: list[str],
) -> None:
    # 在 parse_escapes 模式下，找到第一个「未被反斜杠转义的」= 或 :
    if parse_escapes:
        key, value = _split_escaped(line)
    else:
        m = _SPLIT_RE.search(line)
        if not m:
            return
        key = line[:m.start()].strip()
        value = line[m.start() + 1:].strip()

    if not key:
        return

    if parse_escapes:
        key = _unescape(key)
        value = _unescape(value)

    if key in data:
        warnings.append(f"重复key: {key!r}（值将被覆盖）")

    data[key] = value


def _split_escaped(line: str) -> tuple[str, str]:
    """找到第一个未转义的 = 或 : 并拆分。"""
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            i += 2  # 跳过转义序列
            continue
        if line[i] in "=:":
            return line[:i].strip(), line[i + 1:].strip()
        i += 1
    return line.strip(), ""


def _unescape(text: str) -> str:
    """处理 Java Properties 转义序列。"""
    result = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            c = text[i + 1]
            if c == "n":
                result.append("\n")
            elif c == "t":
                result.append("\t")
            elif c == "r":
                result.append("\r")
            elif c == "u" and i + 5 < len(text):
                try:
                    result.append(chr(int(text[i + 2:i + 6], 16)))
                    i += 5
                except (ValueError, IndexError):
                    result.append(text[i])
            elif c in "\\:=#!":
                result.append(c)
            else:
                result.append(text[i])
            i += 2
            continue
        result.append(text[i])
        i += 1
    return "".join(result)
