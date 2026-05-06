# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

> 记录需要改进但未实施的工程问题。

## 高优先级

### 1. `format_checker.py` `_check_punctuation` 中英文间距误报
`_check_punctuation` (L344-349) 对中英文间空格检查无前缀白名单。Patchouli 手册文本（`book.*`、`patchouli.*` 等）中合法的中英文排版空格会被误报为 SUGGEST。需增加可配置前缀白名单。

### 2. 无单元测试
无任何自动化测试。需对关键函数加测试，至少覆盖：
- `FormatChecker._check_placeholder_integrity`
- `FormatChecker._check_special_tags`
- `key_alignment.align_keys`
- `fuzzy_search.calc_similarity` / `levenshtein_distance`
- `terminology_extract.extract_terms`
- `lemma_merge.raw_merge` / `try_rescue_short_term`

### 3. FTS5 索引单例 `_db_instance` 跨运行泄漏
`fuzzy_search.py:137` 中 `_db_instance` 为模块级单例。虽然单次运行中复用索引没问题，但若在同一个进程里多次调用 `fuzzy_search_lines` 并传入不同 `en_data`/`zh_data`，旧索引不会被重建。应传给 pipeline 层管理生命周期，或增加 `rebuild` 参数。

### 4. 多处 CLI 残留（冗余 `main()` 入口）
以下文件各自保留了独立 `main()` + argparse 入口，应统一走 `run.py`：
- `src/checkers/format_checker.py` (L443)
- `src/checkers/terminology_builder.py`
- `src/llm/llm_bridge.py`
- `src/pipeline/review_pipeline.py` (L501)
- `src/reporting/report_generator.py` (L295)
- `src/tools/terminology_extract.py` (L152)
- `src/tools/fuzzy_search.py` (L169)
- `src/tools/pr_aligner.py` (L352)

## 中优先级

### 5. `review_config.json` 多行字符串可读性差
`style_reference`、`review_instruction`、`review_principles`、`merge_system_prompt` 中含 `\n` 转义符，单行 JSON 不易编辑和 diff。可考虑：
- 方案 A：拆为外部 `.txt` 文件加载
- 方案 B：改用 JSON 数组存多行，运行时 join

### 6. Windows 终端 GBK 编码问题
`run.py:20-21` 已有 `isatty()` 检测重新配置 stdout 为 UTF-8，但 PowerShell 管道场景（`python run.py ... | tee output.log`）仍可能乱码。`isatty()` 在管道中返回 False，跳过 reconfigure。需增加 PowerShell 环境检测或提供 `--utf8` 参数。

### 7. `review_pipeline.py` 的 `main()` 使用旧 API 风格
`review_pipeline.py:522-577` 的独立 CLI 入口使用 `--api-key` / `--model` / `--base-url` 参数，而 `run.py` 使用环境变量 + `create_openai_llm_call`。两套入口不一致，容易混淆。`review_pipeline.py` 的 CLI 入口建议直接废弃。

### 8. 占位符检查 `{0}` 风格输出格式错误
`format_checker.py:209` 中 `missing` 变量名 shadow 了上一句的 `missing`，且 `', '.join(missing)` 输出格式可读性差（如 `{0` 而非 `{0}`）。尽管不影响功能，但误导读日志。

## 低优先级

### 9. `report_generator.py` stats 计算可能不准确
`compute_stats()` (L120-136) 中 `passed = total - len(self.verdicts)` 假设所有非 PASS verdict 都在 `self.verdicts` 中。若 `merge_verdicts` 逻辑变更导致部分 PASS 也进入 verdicts，PASS 计数会偏少。`max(passed, explicit_pass)` 的保护不够健壮。

### 10. PR 模式 `_group_mod_files` 对仅删不增的文件处理不完整
`pr_aligner.py:119-128` 中，若 en_us.json 状态为 `removed`，`en_head` 会被设为该路径，但后续 `_raw_get` 从 head SHA 拉取会 404，导致整个模组被跳过（L286-288）。应处理 removed 文件为 `"": {}` 而非跳过。

### 11. `llm_bridge._group_prefix` 返回 `"__default__"` 但无对应 prompt entry
`llm_bridge.py:73-77` 中未匹配到前缀的 key 返回 `"__default__"`，后续查找 `KEY_PREFIX_PROMPTS["__default__"]` 会 KeyError。虽然当前 `build_review_prompt` 中通过 `cfg.DEFAULT_REVIEW_FOCUS` 兜底，但在其他调用点（如 `classify_entries`）可能遗漏。

### 12. `lemma_cache.record` 频次递减可能不准确
`lemma_cache.py:101-106` 中，当 variant 从一个旧 canonical 重定向到新 canonical 时，旧 canonical 的 `_freq` 减 1（不低于 0）。但 variant 对旧 canonical 的实际贡献频次可能 > 1（如果该 variant 之前被多次 lookup/record 过），导致旧 canonical 频次虚高。影响较小，仅影响缓存文件的排序和热度统计。
