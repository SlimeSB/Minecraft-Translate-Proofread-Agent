# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

`python run.py --pr 5979 -o ./output/ --external-dict`

> 279 个单元测试（17 个模块），全部通过。

---

### High

- `terminology_builder.py:101-117` vs `lemma_cache.py:19-43` — `_is_useful_term` / `_is_valid_term` 词法 check 逻辑重复（但底层停用词来源不同，合并需谨慎）

### 类型系统被绕过（大重构）
- 10+ 文件用 `dict[str, Any]` 而非 TypedDict（`VerdictDict` 等形同虚设）
- **pyright 关闭 13 项核心检查** (`pyrightconfig.json`): `reportAssignmentType`, `reportReturnType`, `reportAttributeAccessIssue`, `reportOptionalMemberAccess` 等。`reportArgumentType` ✅ 已修。TypedDict 约束形同虚设。
- **目标**: 逐步启用关键检查项，清理类型标注

---

## 已丢弃（无需处理）

| 项目 | 原因 |
|------|------|
| `shutil.rmtree()` 清空 output 目录 (`pipeline.py:67`) | 设计如此，勿在 `-o` 目录放其他文件即可 |
