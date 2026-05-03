# Minecraft 模组翻译审校工具

程序化自动检查 + LLM 启发式审校的混合架构。90%+ 检查由确定性规则完成，LLM 只处理需要语义判断的条目。

## 快速开始

```bash
cp .env.example .env          # 填入 API key
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o output --dry-run
python run.py --en en_us.json --zh zh_cn.json -o output --no-llm    # 零 token
python run.py --en en_us.json --zh zh_cn.json -o output              # 完整流水线
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `REVIEW_OPENAI_API_KEY` | API key | 无 |
| `REVIEW_OPENAI_BASE_URL` | API 地址 | `https://api.deepseek.com` |
| `REVIEW_OPENAI_MODEL` | 模型 | `deepseek-v4-flash` |

## 项目结构

```
run.py                              # CLI 入口
review_config.json                  # 所有可调参数 + prompt 模板 + 术语停用词
.env.example
src/
├── config.py                       # 配置加载模块（全仓唯一配置来源）
├── pipeline/review_pipeline.py     # 主编排器 Phase 1→4
├── tools/                           # 无状态工具
│   ├── key_alignment.py            # 键对齐 en↔zh
│   ├── fuzzy_search.py             # SQLite FTS5 模糊搜索
│   └── terminology_extract.py      # n-gram 高频词提取
├── checkers/                       # 全自动检查器
│   ├── format_checker.py           # 10 项格式验证
│   └── terminology_builder.py      # 词形分桶 + 缓存归并 + 术语表 + 一致性检查
├── llm/llm_bridge.py               # LLM prompt 构建 + 并行调用 + 429 重试
└── reporting/report_generator.py   # 多来源 verdict 合并 + 报告生成
tests/fixtures/                     # 测试数据
```

## 流水线

```
Phase 1: 键对齐          → 01_alignment.json
Phase 2: 术语提取+归并     → 02_terminology_glossary.json + lemma_cache.json
Phase 3a: 格式检查        → 03_format_verdicts.json         (10 项规则，全是程序)
Phase 3b: 模糊搜索        → 04_fuzzy_results.json           (SQLite FTS5)
Phase 3c: LLM 审校        → 05_llm_verdicts.json            (并行 4 workers, 429退避)
Phase 4: 报告生成         → 06_review_report.json + 07_zh_cn_annotated.json
```

## 自动检查规则（10 项，全部程序化）

1. 占位符完整性（`%d/%s/%f/%n$s/%msg%/{0}` 等，`%1$s`↔`%s` 归一化比对）
2. 特殊标签完整性（`§`/`&`/`$(action)`/HTML/`<br>`/`\n`）
3. tellraw JSON（仅翻译 `text` 键）
4. 中文标点规范（全角标点、半角 `[]`、中英文间距）
5. 省略号格式（禁用 `...`）
6. 能量/体积单位保留（FE、RF、MB）
7. 键盘按键保留（Shift、Ctrl 等）
8. 空翻译检测（`zh==en` 且非代码/专有名词）
9. 声音字幕格式（`主体：声音`）
10. 尾部空格功能冲突

**不再做**：错别字检测、语气/文化引用判断 → 全部交 LLM。

## P3 LLM 审校策略

- **按 key 前缀分组**（`advancements.`、`death.attack.`、`enchantment.` …），每组专属审查重点
- 每批只含一种前缀类型，按 batch_size 切分
- 未匹配前缀归入 `__default__`，用默认 prompt
- 术语表作为强制参考注入到 prompt
- 并行 4 workers，429 自动指数退避

自动通过条件（同时满足全部）：
1. 不属于强制 LLM 类别（进度/死亡信息/魔咒/声音字幕/声音/书籍/实体/状态效果/药水）
2. 键名不含 `.desc/.title/.lore/.tooltip/.flavor/.info/.message/.text`
3. EN ≤80 字符
4. 无自动检查 verdict

## P2 术语表

纯程序化，不调 LLM 做翻译：
1. 从 EN 提取 unigrams/bigrams/trigrams，停用词过滤
2. 原始词面分桶 → LemmaCache 查表归并（持续学习）→ 模糊聚类 → LLM 裁决同形异体
3. 按归并后频次 ≥5 + 共识 ≥60% 构建术语表（仅从事物名称条目取中文，描述性条目排除）
4. `\b` 词边界匹配检查一致性，标记不一致条目

缓存 `lemma_cache.json` 每次 LLM 裁决后写入，跨次运行复用。

## 配置

所有硬编码 prompt 已移至 `review_config.json`。修改此文件即可调整：
- 审查重点 / 风格参考 / 普适原则
- 术语阈值 / 聚类参数
- key 前缀分组规则
- LLM 必选前缀列表

`src/config.py` 是代码侧加载入口，`terminology_builder.py`、`llm_bridge.py` 统一从此读取。

## 输出文件

| 文件 | 说明 |
|------|------|
| `01_alignment.json` | 键对齐 |
| `02_terminology_glossary.json` | 纯程序术语表 `[{en, zh}]` |
| `03_format_verdicts.json` | 自动格式检查 |
| `04_fuzzy_results.json` | FTS5 模糊搜索结果 |
| `05_llm_verdicts.json` | LLM 审校结果 |
| `06_review_report.json` | 最终审校报告（合并去重） |
| `07_zh_cn_annotated.json` | 带 `_comments` 的可读副本 |
| `08_llm_call_log.txt` | LLM prompt/response 完整日志 |
| `lemma_cache.json` | 词形映射缓存（跨次复用） |

## 配置与数据文件

| 文件 | 说明 |
|------|------|
| `review_config.json` | 所有可调参数 + 全部 prompt 模板 + 术语停用词 |
| `.env` | API key（不提交） |
| `.env.example` | 环境变量模板 |
