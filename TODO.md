# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

> 记录需要改进但未实施的工程问题。已修复项移入下方"已修复"节。

## 当前待办

### 1. Windows 终端 GBK 编码问题
`run.py:20-21` 已有 `isatty()` 检测重新配置 stdout 为 UTF-8，但 PowerShell 管道场景（`python run.py ... | tee output.log`）仍可能乱码。`isatty()` 在管道中返回 False，跳过 reconfigure。可增加 `--utf8` 参数或自动检测 PowerShell 环境（`WT_SESSION` 等环境变量）。

## 已修复

| # | 描述 | 提交 |
|---|------|------|
| 8 | 占位符检查 `{0}` 风格输出格式错误 + 变量名覆盖 | `fix: 修复占位符检查 {0} 风格输出格式错误并消除变量名覆盖` |
| 4+7 | 统一 CLI 入口，移除 5 个管道模块的独立 main() | `refactor: 统一CLI入口，移除5个管道模块的独立main()及未使用导入` |
| 11 | `_group_prefix` 返回 `"__default__"` — 已确认所有调用点均有 `.get()` 兜底 | _(无需修复)_ |
| 9 | `report_generator` stats PASS 计数对混入条目不准确 | `fix: 修复report_generator统计PASS计数对混入PASS条目不准确的问题` |
| 1 | 标点检查中英文间距误报，增加可配置前缀白名单 | `fix: 标点检查增加可配置前缀白名单，豁免book./patchouli.的中英文间距检查` |
| 10 | PR 模式 `removed` 文件 404 导致整个模组被跳过 | `fix: PR模式处理removed文件，避免404导致整个模组被跳过` |
| 12 | `lemma_cache.record` 重映射时频次递减不准确 | `fix: lemma_cache.record重映射时按实际贡献次数递减旧canonical频次` |
| 3 | FTS5 索引单例数据不变时不重建，数据变更时自动重建 | `fix: FTS5索引单例在数据变更时自动重建，避免跨运行泄漏` |
| 5 | `review_config.json` 多行文本改用数组格式 | `refactor: review_config.json多行文本改用数组格式，提升可编辑性和diff可读性` |
| 2 | 关键函数单元测试 (68 tests) | `test: 添加format_checker/key_alignment/fuzzy_search/terminology_extract/lemma_merge单元测试68个` |

### 测试期间发现并修复的新 bug

| # | 描述 | 提交 |
|---|------|------|
| — | `key_alignment.py` 未过滤代码常量到 suspicious_untranslated | 含在测试提交中 |
| — | `format_checker._check_placeholder_integrity` 未检查 `%1$s` 位置占位符 | 含在测试提交中 |
