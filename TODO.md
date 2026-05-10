# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

`python run.py --pr 5979 -o ./output/ --external-dict`

> 291 个单元测试（18 个模块），全部通过。

---

## 待办

### 类型系统
- [ ] 逐步启用 pyright 关键检查项（当前关闭 13 项：`reportAssignmentType`, `reportReturnType`, `reportAttributeAccessIssue`, `reportOptionalMemberAccess` 等；✅ `reportArgumentType` 已修）
- [ ] `storage/database.py`: 从 `Mapping[str, Any]` 迁移到 TypedDict（SQLite 行数据形状多变，建议从简单边界开始）
- [ ] `src/tools/pr/` 模块: 4 文件全用 `dict[str, Any]`，需先定型 `PRAlignmentEntryDict` 字段再逐文件迁移

### 代码重复
- [ ] 合并两套 LLM JSON 解析器（`bridge.py` 和 `terminology_builder.py`）
- [ ] 清理多处重复的 `if __name__ == "__main__"` + argparse 样板代码

### 架构
- [ ] 消除 `asyncio.run()` 反模式（`bridge.py` 同步方法内调 async，无法在已有事件循环中复用）
- [ ] LLM 并发改用真异步 IO（当前通过线程池包装，非真异步）

### 测试
- [ ] Phase 4 过滤器缺测试（仅 33 行，是审查管线最后关卡）
- [ ] `external.py`（外部词典，153 行）零单元测试

### 其他
- [ ] 消除 `client.py` 闭包可变状态（`call_count = [0]`、`usage = {}`，脆弱且不可重入）

---

## 已完成

- [x] `_is_useful_term` / `_is_valid_term` 词法 check 逻辑重复 → 合并为 `src/tools/term_validation.py`
- [x] `openspec/specs/` 6 个已实现 spec 归档 + typeddict-migration change 归档

## 已丢弃

- [x] `shutil.rmtree()` 清空 output 目录（`pipeline.py:67`）— 设计如此，勿在 `-o` 目录放其他文件即可
