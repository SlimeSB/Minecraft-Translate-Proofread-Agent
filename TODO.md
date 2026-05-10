# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

`python run.py --pr 5979 -o ./output/ --external-dict`

> 291 个单元测试（18 个模块），全部通过。

---

## 待办

### 类型系统
- [ ] `src/tools/pr/` 模块: 4 文件全用 `dict[str, Any]`，需先定型 `PRAlignmentEntryDict` 字段再逐文件迁移
- [ ] `models.py:104` — `AlignmentDict`（`total=True`）赋 `{}`，缺必填字段，pyright 没报只是因为关了 13 项检查
- [ ] `database.py:115` `-> dict`、`key_alignment.py:40` `-> dict`：裸 dict 返回丢失 TypedDict 类型信息（已在`## 未计划`中列了 DB，但 key_alignment 也需修）

### 代码重复
- [ ] 合并两套 LLM JSON 解析器（`bridge.py` 和 `terminology_builder.py`）
- [ ] 清理多处重复的 `if __name__ == "__main__"` + argparse 样板代码
- [ ] 合并两份 `load_json()` 副本（`src/tools/key_alignment.py:40` vs `src/tools/fuzzy_search.py:164`）
- [ ] 合并两份 GBK-safe print 副本（`src/cli.py:29` vs `src/reporting/report_generator.py:15`）

### 架构
- [ ] 消除 `asyncio.run()` 反模式（`bridge.py` 同步方法内调 async，无法在已有事件循环中复用）
- [ ] LLM 并发改用真异步 IO（当前通过线程池包装，非真异步）
- [ ] `format_checker.py:93` — 函数体中间 `from ..tools.code_detection import ...  # noqa: E402`，唯一一处方法内 import，可提至文件顶

### 测试
- [ ] Phase 4 过滤器缺测试（仅 33 行，是审查管线最后关卡）
- [ ] `external.py`（外部词典，153 行）零单元测试

### 其他
- [ ] 消除 `client.py` 闭包可变状态（`call_count = [0]`、`usage = {}`，脆弱且不可重入）
- [ ] 消除死代码：`ALL_VERDICTS`（`models.py:194`）、`create_dry_run_llm_call()`（`client.py:129-132`）、三个 CLI `main()`（`fuzzy_search.py:173`, `key_alignment.py:185`, `terminology_extract.py:156`）
- [ ] `term_validation.py:19,43` — `except ImportError:` 静默吞异常，加载失败返回空集/True，调用方无从知晓
- [ ] `ae2guide:` 硬编码 × 3（`prompts.py:39,186`、`phase3c_review.py`），应提取为配置常量
- [ ] `phase4_filter.py:71` — 变量名 `uncached_pass` 语义拧巴（读作"未缓存过去时"）
- [ ] `phase5_report.py:78` — `len(issues)` 局部变量遮盖 `PipelineContext.issues` 字段，虽无 bug 但混淆
- [ ] `phase3c_review.py:104` — `total_chars` 算出后从未使用，死赋值
- [ ] `client.py:59` — 日志归档日期格式 `%Y%m%d-%H%M%S` 无分隔符，文件名难读

---
## 未计划
- [ ] 逐步启用 pyright 关键检查项（当前关闭 13 项：`reportAssignmentType`, `reportReturnType`, `reportAttributeAccessIssue`, `reportOptionalMemberAccess` 等；✅ `reportArgumentType` 已修）（工程太大，延期）
- [ ] `storage/database.py`: 从 `Mapping[str, Any]` 迁移到 TypedDict（SQLite 行数据形状多变，建议从简单边界开始）（工程太大，延期）

## 已完成

- [x] `_is_useful_term` / `_is_valid_term` 词法 check 逻辑重复 → 合并为 `src/tools/term_validation.py`
- [x] `openspec/specs/` 6 个已实现 spec 归档 + typeddict-migration change 归档

## 已丢弃

- [x] `shutil.rmtree()` 清空 output 目录（`pipeline.py:67`）— 设计如此，勿在 `-o` 目录放其他文件即可
