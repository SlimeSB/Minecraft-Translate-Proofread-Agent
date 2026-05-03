# 待办与优化项

> 记录需要改进但未实施的工程问题。无优先级顺序。

## 高优先级
1. 多词术语不要归并映射到到单词

### 2. `terminology_builder.py` 太长（500+ 行）
建议拆分：`LemmaCache` 独立文件；`_fuzzy_cluster` / `_build_merge_prompt` / `_parse_merge_response` / `_apply_llm_merge` 移到独立模块。

### 3. `format_checker.py` `_check_punctuation` 过于敏感
中英文间距检查在 Patchouli 手册文本中正常但被误报。需要可配置白名单（如 book.* 键忽略间距检查）。

### 4. `_check_keyboard_keys` 对 Enter/End 等词误报
"Enter the cave" 中的 Enter 被当作键盘按键。需要检查键名上下文或限制到 `key.` 前缀条目。

### 5. 并行数 `max_workers=4` 硬编码
应该从 `review_config.json` 读取。
已影响：`LLMBridge.review_batch`、`TerminologyBuilder.build_glossary`。


## 中优先级

### 7. FTS5 索引单例 `_get_db` 全局变量
跨多文件运行可能泄漏。应传给 pipeline 层管理生命周期。

### 8. `review_pipeline.py` 模糊搜索候选过滤
当前仅对前 100 条做模糊搜索。若条目超过 100 条可能遗漏。

### 9. LLM 日志 `08_llm_call_log.txt` 无滚动
长期运行会无限增长。建议按日期分文件或限制行数。

### 10. 无单元测试
目前靠干运行验证。需对 `format_checker`、`_check_placeholder_integrity` 等关键函数加测试。

### 11. `TerminologyBuilder.main()` 独立 CLI 残留
正在被 `review_pipeline` 调用，但自己也保留了一个 argparse CLI（`--en --zh --alignment`）。应清理：是否保留独立运行方式，或统一走 `run.py`。

## 低优先级

### 12. `review_config.json` 中多行字符串可读性
`style_reference` 等配置项中 `\n` 不易编辑。可考虑外部 `.txt` 文件。

### 13. `llm_bridge.py` 仍然有自己的 `main()` CLI
全仓有两个独立 CLI 入口（`run.py` + `llm_bridge.py` 独立运行）。考虑统一。

### 14. Windows 终端 GBK 输出问题
`run.py` 已有 `sys.stdout.isatty()` 检查但 PowerShell 管道仍会乱码。
需要文档说明或自动检测 PowerShell 环境。

### 15. README 流程图可加 mermaid 图
当前纯文本。可加 mermaid 流程图提升可读性。
