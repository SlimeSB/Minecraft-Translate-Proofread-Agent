# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

> 记录需要改进但未实施的工程问题。

## 当前待办

### 1. Windows 终端 GBK 编码问题
`run.py:20-21` 已有 `isatty()` 检测重新配置 stdout 为 UTF-8，但 PowerShell 管道场景（`python run.py ... | tee output.log`）仍可能乱码。可增加 `--utf8` 参数或自动检测 PowerShell 环境（`WT_SESSION` 等环境变量）。

### 2. 原版 key 列表待完善
`data/vanilla_keys.json` 目前仅包含约 300 个示例 key（advancements/biomes/blocks部分），未涵盖全部原版 key。完整列表可从各版本 Minecraft 的 `en_us.json` 提取补全。

### 3. GuideME 文档内容级审校
当前 GuideME 支持仅做「文件级」对齐（按路径匹配中英文 `.md` 文件），未深入到 markdown 内容内部的翻译审校。标记为 `ae2guide:` 前缀的条目作为整篇文档进入 pipeline，LLM 可评审全文翻译质量。

