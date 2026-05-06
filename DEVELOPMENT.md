# 开发文档

## 架构概览

```
run.py                          # CLI 入口，参数解析，模式分发
  │
  ├─ 传统模式                   # --en / --zh (JSON或.lang自动检测)
  ├─ PR 模式                    # --pr [--repo] (JSON/Lang/GuideME)
  ├─ filter-only 模式           # --filter-only
  └─ 构建 LLM callable         # create_openai_llm_call()
       │
       ▼
ReviewPipeline                  # 主编排器，6 阶段流水线
  │
  ├─ Phase 1: Key Alignment
  │   ├─ src/tools/key_alignment.py     (JSON: load_json_clean + align_keys)
  │   └─ src/tools/lang_parser.py       (Lang: load_lang → dict)
  │
  ├─ Phase 2: Terminology
  │   ├─ src/checkers/terminology_builder.py  (主流程)
  │   ├─ src/tools/terminology_extract.py     (N-gram 提取)
  │   ├─ src/checkers/lemma_merge.py          (词形归并)
  │   └─ src/checkers/lemma_cache.py          (缓存)
  │
  ├─ Phase 3a: Format Checking
  │   └─ src/checkers/format_checker.py
  │
  ├─ Phase 3b: Fuzzy Search
  │   └─ src/tools/fuzzy_search.py
  │
  ├─ Phase 3c: LLM Review
  │   ├─ src/llm/llm_bridge.py   (prompt 构建、批量调用、解析)
  │   └─ 外部 LLM API
  │
  ├─ Phase 4: Report Generation
  │   └─ src/reporting/report_generator.py
  │
  └─ Phase 5: Final Filter
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

## 核心模块

### 1. `src/pipeline/review_pipeline.py` — 主编排器

`ReviewPipeline` 类持有所有运行时参数，`run()` 方法串联 Phase 1-5。

```python
pipeline = ReviewPipeline(
    en_path="en_us.json", zh_path="zh_cn.json",
    output_dir="./output/",
    llm_call=my_llm_fn,          # Callable[[str], str]
    no_llm=False,                # 跳过 LLM 阶段
    interactive=False,           # 交互式逐条审校
    dry_run=False,               # 统计但不调 LLM
    min_term_freq=3,             # 术语最低频次
    fuzzy_threshold=60.0,        # 模糊搜索阈值
    batch_size=20,               # LLM 每批条目数
    pr_alignment=None,           # PR 模式的预对齐数据
)
pipeline.run()
```

**关键点**：
- Phase 1 自动检测 `.json` vs `.lang` 格式并调用对应加载器
- Phase 3a 和 Phase 3c 分开：3a 是确定性规则，3c 是 LLM 启发式
- Phase 5 是二次过滤：把 Phase 4 汇总后的所有 verdict 再次发给 LLM，剔除误报
- 各阶段输出中间 JSON 到 `output_dir`，编号 `01_` 到 `07_`

### 2. `src/tools/key_alignment.py` — 键对齐 & 碰撞检测

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

### 3. `src/tools/lang_parser.py` — .lang 文件解析

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

### 4. `src/checkers/format_checker.py` — 格式检查

10 项确定性检查，全部纯规则：

| 检查项 | 方法 | 规则 |
|--------|------|------|
| 空翻译 | `_check_empty` | zh 为空字符串 → FAIL |
| 唱片名 | `_check_music_disc` | 须符合 `音乐唱片 - 曲名` 格式 |
| 占位符 | `_check_placeholders` | `%d/%s/%f`, `%n$s`, `%msg%`, `{0}` 个数一致 |
| 特殊标签 | `_check_special_tags` | `§` 颜色码、`$(action)`、HTML、`<br>`、`\n` 数量一致 |
| tellraw | `_check_tellraw` | 仅翻译 `"text"` 字段，其余保留原文 |
| 标点 | `_check_punctuation` | 中英间距（可配置白名单）、省略号、标点规范 |
| 尾空格 | `_check_trailing` | 尾随空格一致性 |
| 能量单位 | `_check_energy_units` | FE/RF/MB 等保留原文 |
| 声音字幕 | `_check_subtitle_format` | `主体：声音` 格式 |
| 树木名 | `_check_tree_naming` | 树名一致性 |

### 5. 术语构建 & 模糊搜索 & LLM 桥接 & 报告生成

参见架构图，核心逻辑未变。

### 6. `src/tools/pr/` — PR 对齐（模块化架构）

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

### 7. `src/config.py` — 配置加载

从 `review_config.json` 读取所有配置，新增键需加入 `_KNOWN_KEYS` 否则启动告警。多行文本字段支持字符串数组格式（运行时 `\n` join）。

新增配置键：

| 键 | 说明 |
|----|------|
| `punctuation_spacing_whitelist` | 中英文间距检查豁免前缀 |
| `default_pr_repo` | PR 模式默认仓库 |

## 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `REVIEW_OPENAI_API_KEY` | 是 | - | OpenAI 兼容 API 密钥 |
| `REVIEW_OPENAI_BASE_URL` | 否 | `https://api.deepseek.com` | API 端点 |
| `REVIEW_OPENAI_MODEL` | 否 | `deepseek-v4-flash` | 模型名 |

## 数据流

```
JSON/Lang文件
        │
        ├─ load_json_clean() / load_lang()  (自动检测格式)
        ▼
   key_alignment ──── 01_alignment.json
        │                     │
        │ matched_entries      │ missing / extra / suspicious
        ├─ terminology_builder │   + vanilla_collisions
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

pip install openai
cp .env.example .env

# 运行测试 (79 tests)
python -m unittest discover tests -v

# 手工验证
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/ --dry-run
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/ --no-llm
```

## 扩展指南

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
