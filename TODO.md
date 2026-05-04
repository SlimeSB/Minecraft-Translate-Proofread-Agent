# 待办与优化项

快速运行：python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/

> 记录需要改进但未实施的工程问题。统一入口为 `run.py`。

## 高优先级

### 1. `LemmaCache` 应独立文件 ✅
已在 `src/checkers/lemma_cache.py`，`terminology_builder.py` 通过 import 使用。

### 2. `format_checker.py` `_check_punctuation` 过于敏感
中英文间距检查在 Patchouli 手册文本中正常但被误报。需要可配置 key 前缀白名单（如 `book.*` 键忽略间距检查）。

### 3. 并行数 `max_workers=4` 硬编码 ✅
现已从 `review_config.json` 读取，默认 4。`LLMBridge.review_batch` 参数默认 `None` 时从配置取。

### 4. `review_config.json` 缺少 schema 校验 ✅
`config.py` 不再静默吞掉未知键，启动时输出 stderr 警告。


## 中优先级

### 5. FTS5 索引单例 `_get_db` 全局变量
`fuzzy_search.py` 中 `_db_instance` 为模块级单例，跨多次运行可能泄漏。应传给 pipeline 层管理生命周期。

### 6. `review_pipeline.py` 模糊搜索候选过滤
当前仅对前 100 条做模糊搜索。若条目超过 100 条可能遗漏。

### 7. 无单元测试
目前靠干运行验证。需对 `format_checker`、`_check_placeholder_integrity` 等关键函数加测试。

### 8. 多处 CLI 残留
以下文件各自保留了 `main()` argparse CLI 入口，应统一走 `run.py`：
- `src/checkers/terminology_builder.py`
- `src/llm/llm_bridge.py`
- `src/pipeline/review_pipeline.py`
- `src/checkers/format_checker.py`


## 低优先级

### 9. `review_config.json` 中多行字符串可读性
`style_reference`、`review_instruction`、`review_principles`、`merge_system_prompt` 中含 `\n`，不易编辑。可考虑外部 `.txt` 文件。

### 10. Windows 终端 GBK 输出问题
`run.py` 已有 `sys.stdout.isatty()` 检查但 PowerShell 管道仍会乱码。需要文档说明或自动检测 PowerShell 环境。

### 11. README 流程图可加 mermaid 图
当前纯文本。可加 mermaid 流程图提升可读性。
