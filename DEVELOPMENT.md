# 开发文档

## 架构概览

```
run.py                          # CLI 入口，参数解析，模式分发
  │
  ├─ 传统模式                   # --en / --zh
  ├─ PR 模式                    # --pr / --repo
  ├─ filter-only 模式           # --filter-only
  └─ 构建 LLM callable         # create_openai_llm_call()
       │
       ▼
ReviewPipeline                  # 主编排器，6 阶段流水线
  │
  ├─ Phase 1: Key Alignment
  │   └─ src/tools/key_alignment.py
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
- Phase 3a 和 Phase 3c 分开：3a 是确定性规则，3c 是 LLM 启发式。Phase 3c **只传入 3a 无法确定 PASS 的条目**。
- Phase 5 是二次过滤：把 Phase 4 汇总后的所有 verdict 再次发给 LLM，剔除误报。
- 各阶段输出中间 JSON 到 `output_dir`，编号 `01_` 到 `07_`。

### 2. `src/tools/key_alignment.py` — 键对齐

核心函数：`align_keys(en_data, zh_data) -> dict`

```python
{
    "matched_entries": [{"key": ..., "en": ..., "zh": ...}, ...],
    "missing_zh":       [{"key": ..., "en": ...}, ...],
    "extra_zh":         [{"key": ..., "zh": ...}, ...],
    "suspicious_untranslated": [{"key": ..., "reason": ...}, ...],
    "stats": {...}
}
```

**判断逻辑**：
- `key in en and key in zh` → matched
- `key in en but not zh` → missing_zh（未翻译）
- `key in zh but not en` → extra_zh（多余键）
- `en == zh` 且值非代码/专有名词 → suspicious_untranslated（疑似未翻）

### 3. `src/checkers/format_checker.py` — 格式检查

`FormatChecker` 类对每条 matched entry 执行以下检查：

| 检查项 | 方法 | 规则 |
|--------|------|------|
| 空翻译 | `_check_empty` | zh 为空字符串 → FAIL |
| 唱片名 | `_check_music_disc` | 须符合 `音乐唱片 - 曲名` 格式 |
| 占位符 | `_check_placeholders` | `%d/%s/%f`, `%n$s`, `%msg%`, `{0}` 个数一致 |
| 特殊标签 | `_check_special_tags` | `§` 颜色码、`$(action)`、HTML、`<br>`、`\n` 数量一致 |
| tellraw | `_check_tellraw` | 仅翻译 `"text"` 字段，其余保留原文 |
| 标点 | `_check_punctuation` | 中英间距、省略号格式（`…` vs `...`）、标点规范 |
| 尾空格 | `_check_trailing` | 尾随空格一致性 |
| 能量单位 | `_check_energy_units` | FE/RF/MB 等保留原文 |
| 声音字幕 | `_check_subtitle_format` | `主体：声音` 格式 |
| 树木名 | `_check_tree_naming` | 树名一致性 |

所有检查均为纯规则，不依赖 LLM。返回 verdict 列表。

### 4. `src/checkers/terminology_builder.py` — 术语构建

`TerminologyBuilder` 是整个 Phase 2 的主入口，流程：

```
extract_terms(en_data)
  → N-gram 提取（unigram/bigram/trigram + 频次统计）

raw_merge(terms)
  → 规则粗筛：小写归一化、短术语包含检查

apply_cache_merge(merged)
  → 命中 lemma_cache.json 中已学习的归并

fuzzy_cluster(remaining)
  → 模糊搜索聚类（同一语义的不同拼写形式）

apply_llm_merge(clusters, llm_call)
  → LLM 裁决同形异体，结果写入缓存

build_glossary(merged_terms, zh_data)
  → 构建术语表，记录各术语的中文翻译映射

check_consistency(glossary)
  → 检查术语翻译一致性，生成 term verdicts
```

**三级归并策略**：
1. **规则** — 小写归一化、前缀/后缀剥离
2. **模糊** — Levenshtein + FTS5 聚类
3. **LLM** — 仅对模糊聚类后的候选群做裁决，节约 token

**术语表结构**：
```json
{
  "term": {"en": "...", "zh_canonical": "...", "freq": 5, "zh_variants": {...}},
  "inconsistencies": [{"key": "...", "expected": "...", "found": "...", "verdict": "FAIL"}]
}
```

### 5. `src/tools/fuzzy_search.py` — 翻译记忆搜索

- **SQLite FTS5** 在内存中构建全量 `en_us.json` 倒排索引
- `fuzzy_search_lines(query, en_data, zh_data, threshold, top_n)`:
  1. FTS5 prefix token 匹配获取候选
  2. 对候选按 Levenshtein 距离排序
  3. 返回 `top_n` 条相似原文及中文翻译
- `_db_instance` 是模块级单例，复用同一索引（**已知问题**：跨多次运行泄漏，见 TODO #5）

### 6. `src/llm/llm_bridge.py` — LLM 桥接

核心类 `LLMBridge`：

```python
bridge = LLMBridge(llm_call: Callable[[str], str])
verdicts = bridge.review_batch(entries, fuzzy_results, ...)  # Phase 3c
filtered, discards = bridge.filter_verdicts(verdicts)        # Phase 5
```

**关键功能**：

- **`build_review_prompt(entries, ...)`**：
  - 按 key 前缀分组，注入对应的审查重点
  - 检测键盘按键/鼠标操作，动态补充指南
  - 注入术语表、风格参考、模糊搜索结果
  - 根据 `llm_required_prefixes` 标记强制 LLM 审校条目
- **`filter_for_llm(entries, format_verdicts)`**：筛选出需要 LLM 审校的条目（缩小范围）
- **`create_openai_llm_call(api_key, model, base_url)`**：工厂函数，返回 `openai.chat.completions.create` 的封装
- **`merge_multipart_entries(entries)`**：合并 `en_*_part` / `zh_*_part` 拆分条目（来自 PR 模式）

**Prompt 结构**（每条审校请求）：

```
[系统 prompt]
你是一位 Minecraft 模组简中翻译审校专家...
（含风格参考、审校原则）

[按键/鼠标指南]（如有）
检测到键盘按键… / 检测到鼠标操作…

[条目 #1]
【物品】key: item.example.shield
EN: Gold Shield
ZH: 金盾牌

[审查重点: item.*] 物品名须材质+核心名词…

[模糊搜索结果]
相似原文 | 相似译文 | 相似度
...
```

**LLM 可替换**：`llm_call` 是任意 `Callable[[str], str]`，可以是 OpenAI、Azure、本地模型等。

### 7. `src/reporting/report_generator.py` — 报告生成

合并 Phase 3a、术语检查、Phase 3c 的所有 verdict：

- **合并策略**：优先级 FAIL > REVIEW > SUGGEST。同优先级时 LLM 来源优先于 format 优先于 term。
- 去重：按 key 去重
- 输出 `review_report.json` 和 `zh_cn_annotated.json`

### 8. `src/tools/pr_aligner.py` — PR 模式对齐

- 通过 GitHub API 拉取 PR diff
- 对齐 4 文件（旧 en / 新 en / 旧 zh / 新 zh）
- 检测「en 改了但 zh 没改」的条目
- 返回与 `key_alignment` 兼容的数据结构

### 9. `src/config.py` — 配置加载

从 `review_config.json` 读取所有配置，提供缓存的 `get(key, default)` 接口。

**已知键清单**（新增键需加入 `_KNOWN_KEYS`，否则启动时告警）：

| 类别 | 键 | 说明 |
|------|-----|------|
| 术语 | `term_min_freq`, `term_min_consensus`, `term_max_zh_len`, `term_max_en_len`, `term_consensus_min_total` | 术语提取阈值 |
| 聚类 | `fuzzy_cluster_threshold`, `fuzzy_cluster_top_n` | 词形模糊聚类参数 |
| 黑名单 | `term_blacklist` | 排除的英文 stop words |
| Prompt | `review_system_prompt`, `review_instruction`, `review_principles`, `style_reference`, `merge_system_prompt`, `review_header_prefix` | LLM prompt 模板 |
| 过滤 | `filter_system_prompt`, `filter_instruction`, `filter_batch_size` | Phase 5 配置 |
| 分类 | `key_prefix_prompts`, `llm_required_prefixes`, `desc_key_suffixes`, `default_review_focus` | key 分类与审查策略 |
| 资源 | `max_workers` | LLM 异步并发数 |
| PR | `pr_change_context_prompt` | PR 模式特定指南 |
| 动态 | `keyboard_guidance`, `mouse_guidance` | 输入设备检测补充指南 |

## 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `REVIEW_OPENAI_API_KEY` | 是 | - | OpenAI 兼容 API 密钥 |
| `REVIEW_OPENAI_BASE_URL` | 否 | `https://api.deepseek.com` | API 端点 |
| `REVIEW_OPENAI_MODEL` | 否 | `deepseek-v4-flash` | 模型名 |

## 数据流

```
en_us.json + zh_cn.json
        │
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

## 术语表词形归并详细流程

```
en_us.json
  → extract_terms()           # N-gram 提取 + 频次/分布统计
  → raw_merge()               # 规则粗并：小写归一化、短词包含关系
  → apply_cache_merge()       # 命中 lemma_cache.json
  → fuzzy_cluster()           # 模糊搜索发现同源候选群
  → build_merge_prompt()      # 构建 LLM 裁决 prompt
  → parse_merge_response()    # 解析 LLM 响应
  → apply_llm_merge()         # 应用裁决结果
  → 写入 lemma_cache.json     # 持续学习
  → build_glossary()          # 构建术语-译文映射
  → check_consistency()       # 评审翻译一致性 → 产出 verdicts
```

`try_rescue_short_term()` 处理中文互斥救援：当短英文术语是长术语的子串，但两者不应指向同一中文时，重新统计排除长术语包含的 key。

## 开发环境

```bash
# 创建虚拟环境
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
source venv/bin/activate       # Linux/macOS

# 安装依赖
pip install openai

# 配置 API
cp .env.example .env
# 编辑 .env

# 运行测试（目前无单元测试，用 fixtures 做手工验证）
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/ --dry-run
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/ --no-llm
```

## 已知问题 & TODO

参考 [TODO.md](./TODO.md) 完整列表，核心待办：

1. **单元测试缺失** — `format_checker` 的关键函数须补测试
2. **标点检查过于敏感** — Patchouli 手册文本的合理空格被误报，需增加 key 前缀白名单
3. **FTS5 单例生命周期** — `fuzzy_search.py` 中 `_db_instance` 全局变量跨多次运行泄漏
4. **多处 CLI 残留** — 部分模块有自己的 `main()` + argparse，应统一走 `run.py`
5. **模糊搜索仅前 100 条** — 条目超过 100 可能遗漏相似项
6. **Windows GBK 终端乱码** — `run.py` 已有 `isatty()` 检查，但 PowerShell 管道仍有编码问题

## 添加新的格式检查

1. 在 `src/checkers/format_checker.py` 的 `FormatChecker` 类中添加 `_check_xxx()` 方法
2. 方法签名：`def _check_xxx(self, entry: dict) -> dict | None`，返回 verdict dict 或 `None`（PASS）
3. 在 `check_entry()` 方法中调用它
4. 如需配置项，添加到 `review_config.json` 和 `config.py` 的 `_KNOWN_KEYS`

## 添加新的 key 前缀审查策略

1. 在 `review_config.json` 的 `key_prefix_prompts` 中添加映射：
   ```json
   "myprefix.": ["类别标签", "审查重点描述"]
   ```
2. 如需强制 LLM 审校，添加到 `llm_required_prefixes`
3. 如需特定后缀标识描述性文本，添加到 `desc_key_suffixes`

## 添加 PR 模式新仓库支持

PR 模式面向 GitHub 仓库的文件变更评审。核心在 `src/tools/pr_aligner.py`：

- `run_pr_aligner()` 通过 GitHub API（纯 `urllib`）拉取 PR diff
- 解析 4 类文件（旧 en / 新 en / 旧 zh / 新 zh）
- 检测「en 改了 zh 没改」的情况
- 返回兼容 `align_keys()` 的数据结构

要适配新仓库，检查 `pr_aligner.py` 中的文件名匹配逻辑（通常按目录约定 `en_us/` / `zh_cn/` 下的 JSON 文件）。
