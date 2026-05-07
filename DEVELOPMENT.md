# 开发文档

## 架构概览

```
run.py                              # CLI 入口，参数解析，模式分发
  │
  ├─ 传统模式                       # --en / --zh (JSON或.lang自动检测)
  ├─ PR 模式                        # --pr [--repo] (JSON/Lang/GuideME)
  ├─ filter-only 模式               # --filter-only
  └─ 构建 LLM callable             # create_openai_llm_call()
       │
       ▼
ReviewPipeline                      # 薄编排器 (< 80 行)，6 阶段纯函数调用
  │                                 # 所有状态在 PipelineContext 数据类中
  │
  ├─ Phase  1: run_phase1()   ◄── phase1_alignment.py
  │   ├─ src/tools/key_alignment.py     (JSON: load_json_clean + align_keys)
  │   └─ src/tools/lang_parser.py       (Lang: load_lang → dict)
  │
  ├─ Phase  2: run_phase2()   ◄── phase2_terminology.py
  │   ├─ src/checkers/terminology_builder.py  (主流程)
  │   ├─ src/tools/terminology_extract.py     (N-gram 提取)
  │   ├─ src/checkers/lemma_merge.py          (词形归并)
  │   └─ src/checkers/lemma_cache.py          (缓存)
  │
  ├─ Phase 3a: run_phase3a()  ◄── phase3a_format.py
  │   └─ src/checkers/format_checker.py
  │
  ├─ Phase 3b: run_phase3b()  ◄── phase3b_fuzzy.py
  │   └─ src/tools/fuzzy_search.py            (3c 内部调用)
  │
  ├─ Phase 3c: run_phase3c()  ◄── phase3c_review.py
  │   ├─ src/llm/prompts.py       (提示词构建、条目分类、术语覆盖)
  │   ├─ src/llm/bridge.py        (LLMBridge: 异步批处理、过滤、解析)
  │   ├─ src/llm/client.py        (OpenAI 客户端工厂、日志、重试)
  │   └─ 外部 LLM API
  │
  ├─ Phase  4: run_phase4()   ◄── phase4_report.py
  │   └─ src/reporting/report_generator.py
  │
  └─ Phase  5: run_phase5()   ◄── phase5_filter.py
      └─ LLMBridge.filter_verdicts()
```

### PR 模式架构

```
run.py --pr 5979
  │
  └─ src/tools/pr/__init__.py:run_pr_aligner()
       │
       ├─ pr/_http.py          # GitHub API / raw 拉取
       ├─ pr/_lang.py          # JSON 语言文件配对对齐
       └─ pr/_guideme.py       # GuideME 文档配对对齐
```

### 存储层架构

```
┌─────────────────────────────────────────────────┐
│                 pipeline.db                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ alignment│ │ glossary │ │     verdicts     │ │
│  │  (key,   │ │ (en, zh) │ │ (key, phase,     │ │
│  │  en, zh, │ │          │ │  verdict, reason, │ │
│  │  ns…)    │ │          │ │  filtered, …)     │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │  fuzzy   │ │  filter  │ │       meta       │ │
│  │ _results │ │  _cache  │ │  (key, value)    │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
└─────────────────────────────────────────────────┘
```

`src/storage/database.py` — `PipelineDB` 类封装所有数据库操作，各 Phase 通过它读写中间结果。

## 核心模块

### 0. `src/models.py` — 领域模型

`PipelineContext` 数据类承载所有 Phase 间的共享状态，各 Phase 是接收 ctx 的纯函数：

```python
from dataclasses import dataclass

@dataclass
class PipelineContext:
    # 输入
    en_path: Path | None
    zh_path: Path | None
    output_dir: Path

    # LLM 回调
    llm_call: Callable[[str], str] | None

    # 运行选项
    no_llm: bool; interactive: bool; dry_run: bool
    min_term_freq: int; fuzzy_threshold: float; batch_size: int

    # PR 模式
    pr_mode: bool; pr_alignment: dict | None

    # 中间结果（各 Phase 渐进填充）
    en_data: dict[str, str]
    zh_data: dict[str, str]
    alignment: dict[str, Any]
    glossary: list[dict[str, Any]]
    format_verdicts: list[dict[str, Any]]
    term_verdicts: list[dict[str, Any]]
    llm_verdicts: list[dict[str, Any]]
    fuzzy_results_map: dict[str, list[dict[str, Any]]]
```

### 1. `src/pipeline/pipeline.py` — 薄编排器

`ReviewPipeline` 只负责构建 `PipelineContext` 并按顺序调用各 Phase 函数：

```python
class ReviewPipeline:
    def __init__(self, ...):
        self.ctx = PipelineContext(...)

    def run(self):
        run_phase1(self.ctx)    # 键对齐
        run_phase2(self.ctx)    # 术语提取
        run_phase3a(self.ctx)   # 格式检查
        run_phase3c(self.ctx)   # LLM 审校（含筛选+模糊搜索）
        run_phase4(self.ctx)    # 报告生成
        run_phase5(self.ctx)    # 最终过滤
```

各 Phase 函数位于 `src/pipeline/phase*.py`，全部是模块级函数，签名统一为 `f(ctx: PipelineContext) -> None`。

### 2. LLM 层（三文件拆分）

| 文件 | 职责 |
|------|------|
| `src/llm/client.py` (82 行) | `create_openai_llm_call()` — OpenAI 兼容客户端 + 速率限制重试 + 日志滚动 |
| `src/llm/prompts.py` (280 行) | `build_review_prompt()`、`build_filter_prompt()`、`classify_entries()`、`filter_for_llm()`、`merge_multipart_entries()` 等。所有提示词构建与条目筛选逻辑。 |
| `src/llm/bridge.py` (210 行) | `LLMBridge` 类 — `review_batch()`（异步批处理审校）、`filter_verdicts()`（Phase 5 过滤）。`parse_review_response()` — 响应解析。`interactive_entry_review()` — 交互模式。 |

向后兼容：`from src.llm.llm_bridge import ...` 仍然有效，内部重定向到上述模块。

### 3. `src/tools/key_alignment.py` — 键对齐 & 碰撞检测

核心函数：

```python
# 加载 JSON，过滤 _comment* 键，检测重复 key
data, warnings = load_json_clean(path) → tuple[dict, list[str]]

# 键对齐
result = align_keys(en_data, zh_data)
# → {matched_entries, missing_zh, extra_zh, suspicious_untranslated, stats}

# 原版 key 碰撞检测
collisions = check_vanilla_collisions(en_data, "data/vanilla_keys.json")
# → [{key, mod_value}, ...]
```

**判断逻辑**：
- `key in en and key in zh` → matched
- `key in en but not zh` → missing_zh（未翻译）
- `key in zh but not en` → extra_zh（多余键）
- `en == zh` 且值非代码/专有名词 → suspicious_untranslated（疑似未翻）
- `_comment*` 前缀的 key 自动过滤（如 `_comment`、`_comment2`）

### 4. `src/tools/lang_parser.py` — .lang 文件解析

将 `key=value` 格式的旧版语言文件加载为 dict，支持：

- `=` 和 `:` 两种分隔符（第一个生效）
- `#` 和 `!` 开头的注释行
- `#PARSE_ESCAPE` 指令启用 Java Properties 转义模式
- 行尾 `\` 续行
- Unicode 转义（`\uXXXX`）
- 重复 key 报警

```python
data, warnings = load_lang(path)      # 从文件加载
data, warnings = load_lang_text(text) # 从字符串加载
```

### 5. `src/checkers/format_checker.py` — 格式检查

10 项确定性检查，全部纯规则：

| 检查项   | 方法                     | 规则                                                 |
| -------- | ------------------------ | ---------------------------------------------------- |
| 空翻译   | `_check_empty`           | zh 为空字符串 → FAIL                                 |
| 唱片名   | `_check_music_disc`      | 须符合 `音乐唱片 - 曲名` 格式                        |
| 占位符   | `_check_placeholders`    | `%d/%s/%f`, `%n$s`, `%msg%`, `{0}` 个数一致          |
| 特殊标签 | `_check_special_tags`    | `§` 颜色码、`$(action)`、HTML、`<br>`、`\n` 数量一致 |
| tellraw  | `_check_tellraw`         | 仅翻译 `"text"` 字段，其余保留原文                   |
| 标点     | `_check_punctuation`     | 中英间距（可配置白名单）、省略号、标点规范           |
| 尾空格   | `_check_trailing`        | 尾随空格一致性                                       |
| 能量单位 | `_check_energy_units`    | FE/RF/MB 等保留原文                                  |
| 声音字幕 | `_check_subtitle_format` | `主体：声音` 格式                                    |
| 树木名   | `_check_tree_naming`     | 树名一致性                                           |

### 6. `src/reporting/report_generator.py` — 报告生成

`ReportGenerator` 类收集各来源的 verdict，按 key 去重合并，生成：
- `pipeline.db` verdicts 表（phase=`merged`）— 统一审校报告
- `report.md` — Markdown 可读报告
- `namespaces/<ns>/` — 按 namespace 拆分的质量报告

Verdict 优先级：`❌ FAIL`(4) > `🔶 REVIEW`(3) > `⚠️ SUGGEST`(2) > `PASS`(1)。
来源优先级：`llm_review` / `interactive` > `format_check` / `terminology_check`。

### 7. `src/config.py` — 配置加载

从 `review_config.json` 读取所有配置，新增键需加入 `_KNOWN_KEYS` 否则启动告警。多行文本字段支持字符串数组格式（运行时 `\n` join）。

新增配置键：

| 键                              | 说明                   |
| ------------------------------- | ---------------------- |
| `punctuation_spacing_whitelist` | 中英文间距检查豁免前缀 |
| `default_pr_repo`               | PR 模式默认仓库        |

### 8. `src/tools/pr/` — PR 对齐（模块化架构）

```
src/tools/pr/
├── __init__.py     # run_pr_aligner() 编排器
├── _http.py        # GitHub API 拉取 + raw文件获取
├── _lang.py        # JSON语言文件: match() + group_mod_files() + align()
└── _guideme.py     # GuideME文档: match() + align()
```

**添加新对齐器**：在 `pr/` 下新建 `_xxx.py`，实现 `match(path) → dict|None` 和 `align(...)` 函数，然后在 `__init__.py` 的 `run_pr_aligner()` 中调用。

**GuideME 对齐规则**：
- 路径匹配：`ae2guide/_zh_cn/xxx.md` ↔ `ae2guide/xxx.md`
- 以相对路径作为 entry key（如 `ae2guide:crazyguide/ampere_meter.md`）
- 整篇 `.md` 文件内容作为 `en`/`zh` 值

## 环境变量

| 变量                     | 必需 | 默认值                     | 说明                 |
| ------------------------ | ---- | -------------------------- | -------------------- |
| `REVIEW_OPENAI_API_KEY`  | 是   | -                          | OpenAI 兼容 API 密钥 |
| `REVIEW_OPENAI_BASE_URL` | 否   | `https://api.deepseek.com` | API 端点             |
| `REVIEW_OPENAI_MODEL`    | 否   | `deepseek-v4-flash`        | 模型名               |

## 数据流

```
JSON/Lang文件
        │
        ├─ load_json_clean() / load_lang()  (自动检测格式)
        ▼
   key_alignment ──── alignment 表
        │                     │
        │ matched_entries      │ missing / extra / suspicious
        ├─ terminology_builder │
        │  └─ glossary 表 + verdicts(terminology) 表
        │
        ├─ format_checker ───── verdicts(format) 表
        │
        ├─ fuzzy_search ─────── fuzzy_results 表
        │
        ├─ LLM review ───────── verdicts(llm) 表
        │
        ▼
   report_generator ────────── verdicts(merged) 表 + meta 表
        │
        ▼
   final_filter ────────────── verdicts.filtered 字段 + filter_cache 表
        │
        ▼
   report.md / namespaces/<ns>/report.md
```
所有中间数据统一存在 `output/pipeline.db`（单一 SQLite 文件）。
JSON/Lang文件
        │
        ├─ load_json_clean() / load_lang()  (自动检测格式)
        ▼
   key_alignment ──── 01_alignment.json
        │                     │
        │ matched_entries      │ missing / extra / suspicious
        ├─ terminology_builder │
        │  └─ 02_terminology_glossary.json
        │
        ├─ format_checker ───── 03_format_verdicts.json
        │
        ├─ fuzzy_search ─────── 04_fuzzy_results.json
        │
        ├─ LLM review ───────── 05_llm_verdicts.json
        │
        ▼
   report_generator ────────── 06_review_report.json
        │                     zh_cn_annotated.json
        ▼
   final_filter ────────────── 07_filter_discards.json
```

## 开发环境

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows

pip install openai pytest
cp .env.example .env

# 运行测试 (79 tests)
pytest tests/ -v

# 手工验证
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/ --dry-run
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/ --no-llm
```

## 扩展指南

### 添加新的 Pipeline Phase

1. 在 `src/pipeline/` 下新建 `phaseN_xxx.py`
2. 实现函数 `def run_phaseN(ctx: PipelineContext) -> None`
3. 在 `pipeline.py` 的 `ReviewPipeline.run()` 中按顺序调用

Phase 函数是无副作用的（除 I/O 外），修改 `ctx` 的属性来传递数据给下游。

### 添加新的格式检查

1. 在 `src/checkers/format_checker.py` 的 `FormatChecker` 类中添加 `_check_xxx()` 方法
2. 方法签名：`def _check_xxx(self, entry: dict) -> dict | None`
3. 在 `check_entry()` 方法的 `checks` 列表中加入该函数
4. 如需配置项，添加到 `review_config.json` 和 `config.py` 的 `_KNOWN_KEYS`

### 添加新的 key 前缀审查策略

1. `review_config.json` → `key_prefix_prompts` 添加映射
2. 如需强制 LLM 审校 → `llm_required_prefixes`
3. 如需特定后缀标识描述性文本 → `desc_key_suffixes`

### 添加新的 PR 对齐器类型

1. 在 `src/tools/pr/` 下新建 `_xxx.py`，实现：
   - `match(path: str) -> dict | None` — 匹配文件路径
   - `align(changed_files, raw_base, raw_head, raw_get_fn, token) -> (entries, warnings)` — 对齐逻辑
2. 在 `src/tools/pr/__init__.py` 的 `run_pr_aligner()` 中调用新对齐器
3. entry 格式：`{key, en, zh, old_en?, old_zh?, review_type}`
