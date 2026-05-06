# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

> 记录需要改进但未实施的工程问题。已修复项移入下方"已修复"节。

## 当前待办

### 1. Windows 终端 GBK 编码问题
`run.py:20-21` 已有 `isatty()` 检测重新配置 stdout 为 UTF-8，但 PowerShell 管道场景（`python run.py ... | tee output.log`）仍可能乱码。`isatty()` 在管道中返回 False，跳过 reconfigure。可增加 `--utf8` 参数或自动检测 PowerShell 环境（`WT_SESSION` 等环境变量）。


### 测试期间发现并修复的新 bug

| #   | 描述                                                                   | 提交           |
| --- | ---------------------------------------------------------------------- | -------------- |
| —   | `key_alignment.py` 未过滤代码常量到 suspicious_untranslated            | 含在测试提交中 |
| —   | `format_checker._check_placeholder_integrity` 未检查 `%1$s` 位置占位符 | 含在测试提交中 |

## 新功能

1. 加原版key的撞key报警
key放到一个外部json文件中

2. lang文件支持
lang文件是 key=value 格式的文件
见 外部参考.md

3. guideme支持+对齐器更好的参数
随着对齐器越来越多，需要优化结构
对齐器名成为可选参数。pr对齐的，仓库硬编码到文件里，cli只传 pr 号

4. json _comment支持
   有的json里面会用"_comment"或"_comment前缀"作为注释，注意识别，不要往后传。
   出现重复key的时候报警