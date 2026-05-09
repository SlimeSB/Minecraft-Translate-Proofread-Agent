# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

`python run.py --pr 5979 -o ./output/ --external-dict`

> 279 个单元测试（17 个模块），全部通过。

---

## 刚修复

- ~~LLM 日志加 call_id 对齐 request/response，filter 不再单开日志~~
- ~~DEVELOPMENT.md/AGENTS.md/README.md 三文件同步代码现状~~

---

## Critical（3 项）

- **`lemma_merge.py:198` — `parse_merge_response()` silent `except: pass`** — JSON 解析失败静默吞错，LLM 归并结果直接被丢弃。
- **`pipeline.py:26-43` — `ReviewPipeline.__init__()` 14 个参数** — 应改用 config 对象或 builder 模式。
- **`phase4_filter.py:98` — 冗余 `get` 调用 bug**: `v.get("zh_current") or v.get("zh_current", "")` — 两个调用完全一样。

---

## High（24 项）

### 函数过长
- `phase3c_review.py:27-131` — `run_phase3c()` 105 行，干/交互/LLM/no-LLM 四条路径交织
- `terminology_extract.py:49-160` — `extract_terms()` 112 行
- `client.py:13-117` — `create_openai_llm_call()` 105 行 + 嵌套 `call()` 闭包
- `terminology_builder.py:216-295` — `llm_verify_glossary()` 80 行
- `pr/_guideme.py:27-112` — `align()` 86 行
- `pr/__init__.py:140-211` — `_write_pr_output()` 72 行
- `bridge.py:237-310` — `filter_verdicts()` 74 行 + 内嵌 `_run_all` 49 行
- `phase4_filter.py:16-91` — `run_phase4()` 76 行
- `report_generator.py:135-205` — `build_report()` 71 行
- `lemma_merge.py:214-278` — `try_rescue_short_term()` 65 行

### 重复代码
- `phase5_report.py:50-75 vs 78-104` — `_group_by_namespace` / `_generate_namespace_reports` namespace 提取 ~15 行一致
- `bridge.py:127-167 vs 253-301` — `_batch_process` vs `_run_all` 重复实现 Semaphore + as_completed 模式
- `phase3c_review.py:70-93 vs 98-115` — 主条目/未翻译 两条分支的 4 路径选择逻辑重复
- `pr/_lang.py:13-23` vs `pr/_guideme.py:13-24` — `match()` 正则路径匹配几乎一样
- `terminology_builder.py:101-117` vs `lemma_cache.py:19-43` — `_is_useful_term` / `_is_valid_term` 词法 check 逻辑重复

### 配置/默认值不一致
- `run.py:156` — `--min-term-freq default=3` vs config `term_min_freq: 5`
- `run.py:158` — `--batch-size default=20` vs config `review_batch_size: 25`
- `phase2_terminology.py:21` — `tb.extract(min_freq=2)` 硬编码，不用 config；`max_ngram=3` 也无配置入口
- `phase3c_review.py:99` — 未翻译队列 `batch_size=1` 硬编码
- `phase1_alignment.py:35` — PR 条目 `"format": "json"` 默认值硬编码
- `external.py:13-14` — `DEFAULT_DB_PATH` / `DEFAULT_LEMMA_PATH` 硬编码
- `lemma_cache.py:16` — `DEFAULT_CACHE_PATH = "data/lemma_cache.json"` 硬编码

### 日志不规范
- `cli.py` 整文件 106 行全用 `safe_print()`，绕过 `info()/warn()`

### 全局状态/单例
- `fuzzy_search.py:141-152` — `_db_instance` 模块级单例，不可测试
- `pr/_http.py:9` — `_TOKEN_WARNED` 模块级可変 flag
- `external.py:18` — `_STOP_WORDS` 模块级可变 set
- `client.py:36,39-44` — `call_count`, `usage` 闭包内 mutable 对象

### 类型系统被绕过
- 10+ 文件用 `dict[str, Any]` 而非 TypedDict（`VerdictDict` 等形同虚设）+ pyright 关闭 `reportArgumentType` / `reportReturnType`

---

## Medium（19 项）

### Silent error swallowing
- `config.py:24` — 配置加载失败静默返回空 dict
- `lemma_cache.py:76-78` — 缓存加载失败静默重置
- `external.py:28,82-83` — `except Exception` 太宽 + lemma 缓存加载失败静默重置
- `bridge.py:66-67,73-74` — 两层 `except json.JSONDecodeError: pass`（虽然后续有 fallback）
- `client.py:93` — `except Exception` 太宽
- `terminology_builder.py:81-83,437-438` — JSON 解析 `except: arr=[]` 无 warn；LLM 归并 `except Exception` 太宽

### 多处 `print()` 而非 `info()/warn()`
- `run.py:80,100,105-142` — 耗时/用量 `print()`
- `run.py:167,170,178,183,200,250,255-256` — 错误 `print(file=sys.stderr)`
- `config.py:34-37` — `_validate()` 中 `print(file=sys.stderr)`
- `pr/_http.py:16-18,80` — token 警告/重试 `print()`
- `external.py:49,67` — 词典加载 `print()`
- `scripts/*.py` — 多个脚本用 `print()`

### 未使用的 import
- `report_generator.py:10,13` — `import json` 和 `from pathlib import Path`
- `key_alignment.py:31,33,34` — `argparse`, `re`, `sys`（仅 CLI main 用）
- `fuzzy_search.py:11,13-16` — `argparse`, `os`, `sys`, `tempfile`
- `terminology_extract.py:16-20` — `argparse`, `json`, `sys`

### import 时求值
- `config.py:126-175` — 模块级常量 `DESC_KEY_SUFFIXES` 等在 import 时定死，运行时改配置不生效

### God class
- `terminology_builder.py:360-478` — `TerminologyBuilder` 118 行 10 方法（提取+归并+表构建+一致性）
- `format_checker.py:111-401` — `FormatChecker` 290 行 11 方法（10 项检查全在类里）
- `database.py:79-286` — `PipelineDB` 207 行 18 方法（6 张表 CRUD）
- `report_generator.py:101-240` — `ReportGenerator` 140 行（报告构建 + 控制台打印混在一起）

### 错误处理不一致
- **退避策略两套**：`client.py` 指数退避 5/10/20/40/60s vs `bridge.py` 自己的重试循环
- **DB 连接管理不统一**：`run.py:194-197` 手动 `db = PipelineDB(...)` + `db.close()`，其余 Phase 均用 `with` 语法
- 同模块内 silent vs noisy 行为不一致（`config.py` 静默恢复 vs `pr/_http.py` 抛异常）
- 失败时返回值不统一：`pr/_http.py:73` 404 返回空串，同文件 :53 其他 HTTP 错误抛 `RuntimeError`
- `run.py:168,171,179,184` — `_validate_input_files()` 内直接 `sys.exit(1)`，属于库函数风格不应 exit

### 其他
- `config.py:12` — `_cfg_cache` 模块级全局缓存
- `bridge.py:93-101` — `_llm_call_with_retry()` 7 个参数
- `client.py:13-21` — `create_openai_llm_call()` 7 个参数
- `pr/_http.py:8` — `_USER_AGENT` 硬编码
- `pr/__init__.py:191` — `ns_dir.mkdir` 冗余（父目录已由 185 行创建）
- `phase5_report.py:25` — `rg.verdicts = kept` 绕过 `rg.collect()` 和 `merge_verdicts()` 标准化
- `bridge.py:133` — `error_return_fn` 缺类型注解，作为 callable 传但默认 `None`
- `phase3c_review.py:69` — `cfg.get("review_batch_size", 25)` fallback 多余

---

## Low（10 项）

- `key_alignment.py:134` — `"data/MInecraft.db"` 拼写，大写 N（含 `scripts/migrate_minecraft_db.py:136`）
- `lemma_merge.py:185` — `parse_merge_response` fallback `except` 缺 `warn()`
- `phase3a_format.py:25` — PR 模式 `[:60]` 硬截断，应引用 `en_preview_len`
- `key_alignment.py:178` — `[:80]` 硬截断
- `pr/__init__.py:35,95` — `time.sleep(0.1)` API 拉取间隔硬编码
- `pr/__init__.py:134` — `count > 5` 删除警告阈值硬编码
- `phase4_filter.py:96-99` — cache key `[:150]`/`[:200]` 截断长度硬编码
- `bridge.py:211` — `"__llm_error__"` 哨兵 key 硬编码
- `bridge.py:344` — 交互模式 `input("> ")` 提示符硬编码
- `run.py:80,100` — 日期格式 `%Y-%m-%d %H:%M:%S` 两处 `print()` 硬编码

### Critical — 功能影响
- **`shutil.rmtree()` 每次运行清空 output 目录** (`pipeline.py:67`): 设计如此，勿在 `-o` 目录放其他文件

### High — 代码质量
- **pyright 配置了大量 `=false`** (`pyrightconfig.json`): 14 项核心类型检查关闭 (`reportArgumentType`, `reportReturnType` 等)，TypedDict 约束形同虚设
- **LLM 模块无独立测试**: `bridge.py`, `prompts.py`, `client.py` 共约 800+ 行零单元测试覆盖，仅在集成测试间接触及

### Medium — 代码结构
- **`apply_cache_merge()` 和 `apply_llm_merge()` token 子集守卫位置不一致**: 前者在 redirect 构建时预过滤，后者在 `_apply_merge_map` 内过滤。两者均已委托给 `_apply_merge_map`，差异化合理但守卫点不统一

### Low — 风格/一致性
- **模块级全局单例**: `fuzzy_search.py` 的 `_db_instance`、`config.py` 的 `_cfg_cache`，非线程安全但单进程够用
- **`TerminologyBuilder` 类承担过多职责**: 术语提取 + 词形归并 + 表构建 + LLM校验 + 一致性检查，约 441 行 10 方法

### 未测模块（无独立测试文件）
`dictionary/external.py`, `pipeline/phase1-5*.py`, `cli.py`, `tools/pr/__init__.py`