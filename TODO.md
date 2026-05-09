# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

`python run.py --pr 5979 -o ./output/ --external-dict`

> 279 个单元测试（17 个模块），全部通过。

---

## Critical（1 项）

- **`phase4_filter.py:98` — 冗余 `get` 调用 bug**: `v.get("zh_current") or v.get("zh_current", "")` — 两个调用完全一样，第二个 `get` 死代码。

---

## High

### 重复代码
- `phase5_report.py:50-75 vs 78-104` — `_group_by_namespace` / `_generate_namespace_reports` namespace 提取 ~15 行一致
- `terminology_builder.py:101-117` vs `lemma_cache.py:19-43` — `_is_useful_term` / `_is_valid_term` 词法 check 逻辑重复

### 配置/默认值不一致
- `run.py:156` — `--min-term-freq default=3` vs config `term_min_freq: 5`
- `run.py:158` — `--batch-size default=20` vs config `review_batch_size: 25`
- `phase2_terminology.py:21` — `tb.extract(min_freq=2)` 硬编码，不用 config；`max_ngram=3` 也无配置入口

### 类型系统被绕过
- 10+ 文件用 `dict[str, Any]` 而非 TypedDict（`VerdictDict` 等形同虚设）
- **pyright 关闭 13 项核心检查** (`pyrightconfig.json`): `reportAssignmentType`, `reportReturnType`, `reportAttributeAccessIssue`, `reportOptionalMemberAccess` 等。`reportArgumentType` ✅ 已修。TypedDict 约束形同虚设。
- **目标**: 逐步启用关键检查项，清理类型标注

---

## Medium

### Silent error swallowing
- `config.py:24` — 配置加载失败静默返回空 dict
- `lemma_cache.py:76-78` — 缓存加载失败静默重置
- `external.py:82-83` — lemma 缓存加载失败静默重置
- `terminology_builder.py:81-83` — JSON 解析 `except: arr=[]` 无 warn

### 未使用的 import
- `report_generator.py:10,13` — `import json` 和 `from pathlib import Path`
- `key_alignment.py:31,33,34` — `argparse`, `re`, `sys`（仅 CLI main 用）
- `fuzzy_search.py:11,13-16` — `argparse`, `os`, `sys`, `tempfile`
- `terminology_extract.py:16-20` — `argparse`, `json`, `sys`

### 错误处理不一致
- 同模块内 silent vs noisy 行为不一致（`config.py` 静默恢复 vs `pr/_http.py` 抛异常）
- 失败时返回值不统一：`pr/_http.py:73` 404 返回空串，同文件 :53 其他 HTTP 错误抛 `RuntimeError`

### 其他
- `phase5_report.py:25` — `rg.verdicts = kept` 绕过 `rg.collect()` 和 `merge_verdicts()` 标准化

---

## Low（1 项）

- `key_alignment.py:134` — `"data/MInecraft.db"` 拼写，大写 N（含 `scripts/migrate_minecraft_db.py:136`；Linux 上会找不到文件）

---

## 已丢弃（无需处理）

| 项目 | 原因 |
|------|------|
| `shutil.rmtree()` 清空 output 目录 (`pipeline.py:67`) | 设计如此，勿在 `-o` 目录放其他文件即可 |
