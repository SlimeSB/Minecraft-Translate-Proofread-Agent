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

## 新功能（已实现）

| # | 描述 | 提交 |
|---|------|------|
| 4 | JSON _comment 键识别过滤 + 重复key报警 | `feat: JSON语言文件过滤_comment*键，检测重复key并报警` |
| 1 | 原版key碰撞检测 + `data/vanilla_keys.json` | `feat: 添加原版key碰撞检测，data/vanilla_keys.json外部存储原版key列表` |
| 2 | .lang 文件解析器 + Pipeline自动检测格式 | `feat: 支持.lang文件解析(key=value格式)，Pipeline自动检测格式` |
| 3 | GuideME文档对齐 + PR仓库硬编码 | `feat: GuideME文档对齐支持 + PR仓库硬编码，--repo变为可选参数` |

## 已修复bug

| # | 描述 | 提交 |
|---|------|------|
| 8 | 占位符检查 {0} 风格输出格式错误 + 变量名覆盖 | `fix: 修复占位符检查 {0} 风格输出格式错误并消除变量名覆盖` |
| 4+7 | 统一 CLI 入口，移除 5 个管道模块独立 main() | `refactor: 统一CLI入口，移除5个管道模块的独立main()及未使用导入` |
| 9 | report_generator stats PASS 计数不准 | `fix: 修复report_generator统计PASS计数对混入PASS条目不准确的问题` |
| 1 | 标点检查中英文间距误报，增加可配置前缀白名单 | `fix: 标点检查增加可配置前缀白名单，豁免book./patchouli.的中英文间距检查` |
| 10 | PR 模式 removed 文件 404 导致模组被跳过 | `fix: PR模式处理removed文件，避免404导致整个模组被跳过` |
| 12 | lemma_cache.record 频次递减不准确 | `fix: lemma_cache.record重映射时按实际贡献次数递减旧canonical频次` |
| 3 | FTS5 索引单例数据变更时自动重建 | `fix: FTS5索引单例在数据变更时自动重建，避免跨运行泄漏` |
| 5 | review_config.json 多行文本改用数组格式 | `refactor: review_config.json多行文本改用数组格式，提升可编辑性和diff可读性` |
| 2 | 关键函数单元测试 (79 tests) | `test: 添加format_checker/.../lang_parser单元测试79个` |
