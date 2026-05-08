![DEEPSEEK](img/image-1.png)
> 本仓库完全使用 **GitHub Copilot (DeepSeek-V4-Pro)** 辅助开发。

# Minecraft Mod Translation Proofread Agent

Minecraft 模组简中翻译自动化审校工具。对照原文审查译文，自动检测格式错误、术语不一致、语义偏差等问题，并生成结构化审校报告。

支持三种原文格式：**JSON** (`en_us.json`)、**Lang** (`en_us.lang`, `key=value`)、**GuideME** (`ae2guide/*.md`)。

## 特性

- **键对齐** — 自动匹配中英文键，检测缺失/多余/疑似未翻译条目
- **多格式支持** — JSON、Lang（`key=value`）、GuideME 文档全部覆盖
- **术语提取与词库构建** — N-gram 提取 + 词形归并（规则/缓存/模糊/LLM 四级）→ 自动构建术语表并一致性检查；token 真子集守卫防止多词短语被吞入单词
- **程序化格式检查** — 11 项确定性检查（占位符、颜色码、tellraw JSON、标点规范、省略号等），零 LLM 成本
- **LLM 启发式审校** — 仅将歧义/语义问题提交 LLM，大幅降低 token 消耗
- **模糊搜索翻译记忆** — SQLite FTS5 + Levenshtein 发现相似原文的不同翻译
- **PR 模式** — 直接对 GitHub PR diff 做审校，支持 JSON/Lang/GuideME 三种文件类型；术语从 PR 内完整文件提取（非仅 diff）
- **术语表 LLM 校验** — 程序提取术语后，取 1 最长 + 4 最短上下文交 LLM 复核修正
- **原版 key 碰撞检测** — 从 `data/Minecraft.db`（含版本区间）检测模组是否覆盖原版 key
- **外部社区词典** — 按需 SQLite 查询约 90 万条历史翻译，LLM 审校时自动注入参考
- **最终过滤** — Phase 4 再经 LLM 剔除误报（过激的术语/标点问题），驳回的条目改判 PASS；过滤结果持久化缓存（`filter_cache` 表），反复运行跳过已缓存条目

## 快速开始

### 环境要求

- Python 3.11+
- OpenAI 兼容 API（推荐 DeepSeek）

### 安装

```bash
git clone <repo-url>
cd Minecraft-Translate-Proofread-Agent
pip install openai
```

### 外部词典（可选）

可从社区翻译仓库导出 `data/Dict-Sqlite.db`（约 90 万条历史翻译记录），启用后 LLM 审校时自动注入同词条的社区翻译作为参考。  
词典仓库：https://github.com/VM-Chinese-translate-group/i18n-Dict-Extender  
将 Dict-Sqlite.db 放入 data/ 目录

```bash
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --external-dict
```

> 按需 SQLite 查询模式，仅在 Phase 3c LLM 审校阶段生效，不再全量加载到内存。

## 配置

```bash
cp .env.example .env
```

编辑 `.env` 填入密钥（启动时自动加载，无需手动 source）：

```
REVIEW_OPENAI_API_KEY=sk-your-key-here
REVIEW_OPENAI_BASE_URL=https://api.deepseek.com/
REVIEW_OPENAI_MODEL=deepseek-v4-flash
GITHUB_TOKEN=ghp_your_token_here
```

| 变量 | 必需 | 说明 |
|------|------|------|
| `REVIEW_OPENAI_API_KEY` | 是 | OpenAI 兼容 API 密钥 |
| `REVIEW_OPENAI_BASE_URL` | 否 | API 端点（默认 `https://api.deepseek.com`） |
| `REVIEW_OPENAI_MODEL` | 否 | 模型名（默认 `deepseek-v4-flash`） |
| `GITHUB_TOKEN` | 否 | GitHub Token，PR 模式拉取文件避免 60 req/hr 限流 |

## 用法

```bash
# 完整审校（程序化 + LLM）—— JSON 格式
python run.py --en en_us.json --zh zh_cn.json -o ./output/

# .lang 格式（自动检测）
python run.py --en en_us.lang --zh zh_cn.lang -o ./output/

# 仅自动检查（不调 LLM）
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --no-llm

# 干运行（只统计，不调 LLM）
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --dry-run

# 交互模式（逐条手动判定）
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --interactive

# PR 模式（--repo 可选，默认读配置）
python run.py --pr 5979 -o ./output/

# 启用外部社区翻译词典（需先下载 data/Dict-Sqlite.db）
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --external-dict

# 仅重跑最终过滤（使用 pipeline.db 数据）
python run.py --filter-only -o ./output/

# 清除过滤缓存重新跑
sqlite3 output/pipeline.db "DELETE FROM filter_cache;"
python run.py --filter-only -o ./output/
```

### 输出

所有数据存入 `--output-dir`（默认 `./output/`）下的单一 SQLite 数据库 `pipeline.db`，外加一份可读 Markdown 报告：

| 文件 | 说明 |
|------|------|
| `pipeline.db` | **单一数据库**，包含所有中间结果（下表可查） |
| `report.md` | 过滤后的可读审校报告 |
| `report.json` | 完整 JSON 数据（仅非 PASS 条目） |
| `<ns>_report.md` | 各命名空间逐条问题清单 |


> PR 模式下所有输出文件写入 `output/pr<N>/` 子目录。

**`pipeline.db` 表结构：**

| 表 | 说明 |
|------|------|
| `alignment` | 键对齐结果（key, en, zh, namespace） |
| `glossary` | 术语表（en → zh） |
| `verdicts` | 所有阶段的判决（按 phase=`format`/`terminology`/`llm`/`merged` 区分） |
| `fuzzy_results` | 模糊搜索结果 |
| `filter_cache` | Phase 4 过滤缓存（可持久复用） |
| `meta` | 统计信息与元数据 |

```bash
# 用任意 SQLite 工具查看
sqlite3 output/pipeline.db ".tables"
sqlite3 output/pipeline.db "SELECT key, verdict, reason FROM verdicts WHERE phase='merged' AND filtered=1"
```

### 审校结论

| 标记 | 含义 |
|------|------|
| PASS | 无问题（不出现在报告中） |
| ⚠️ SUGGEST | 微小改进建议 |
| 🔶 REVIEW | 需人工判断 |
| ❌ FAIL | 确定误译/漏译/格式错误 |

## 配置

`review_config.json` 控制所有审校行为，包括：

- 各 key 前缀的审查重点
- 术语提取阈值
- LLM prompt 模板
- 最终过滤策略
- PR 仓库默认值

详见 [DEVELOPMENT.md](./DEVELOPMENT.md)。

## 项目结构

```
├── run.py                        # CLI 统一入口
├── review_config.json            # 审校配置
├── data/
│   ├── Minecraft.db              # 原版 key 数据库（碰撞检测 & 版本区间）
│   └── Dict-Sqlite.db            # 外部社区翻译词典（需单独下载）
├── scripts/
│   ├── download_external_dict.py # 下载外部词典
│   └── migrate_minecraft_db.py   # 迁移原版 DB 格式
├── src/
│   ├── models.py                  # PipelineContext / Verdict 数据类
│   ├── config.py                  # 配置加载器
│   ├── storage/
│   │   └── database.py            # PipelineDB — 单一 SQLite 数据库
│   ├── pipeline/
│   │   ├── pipeline.py            # 薄编排器（6 阶段纯函数调用）
│   │   ├── phase1_alignment.py    # Phase 1 键对齐 / PR 数据加载
│   │   ├── phase2_terminology.py  # Phase 2 术语提取与一致性检查
│   │   ├── phase3a_format.py      # Phase 3a 全自动格式检查
│   │   ├── phase3b_fuzzy.py       # Phase 3b 模糊搜索
│   │   ├── phase3c_review.py      # Phase 3c LLM 审校
│   │   ├── phase4_filter.py       # Phase 4 最终 LLM 过滤（写回 DB）
│   │   ├── phase5_report.py      # Phase 5 报告生成（从 DB 加载）
│   │   └── filter_cache.py        # 过滤缓存兼容层（委托 PipelineDB）
│   ├── checkers/
│   │   ├── format_checker.py      # 全自动格式验证
│   │   ├── terminology_builder.py # 术语提取 & 一致性检查
│   │   ├── lemma_merge.py         # 词形归并逻辑
│   │   └── lemma_cache.py         # 词形缓存
│   ├── dictionary/
│   │   ├── __init__.py
│   │   └── external.py            # 外部词典加载与查询
│   ├── llm/
│   │   ├── __init__.py            # re-export 层
│   │   ├── client.py              # OpenAI 客户端工厂 + 日志/重试
│   │   ├── prompts.py             # 提示词构建、条目分类、术语覆盖检查
│   │   └── bridge.py              # LLMBridge: 异步批处理、过滤、解析、交互
│   ├── reporting/
│   │   └── report_generator.py    # 报告生成 & 合并
│   └── tools/
│       ├── key_alignment.py       # 键对齐 & 原版碰撞检测
│       ├── lang_parser.py         # .lang 文件解析器
│       ├── terminology_extract.py # N-gram 术语提取
│       ├── fuzzy_search.py        # SQLite FTS5 模糊搜索
│       └── pr/                    # PR 对齐模块化架构
│           ├── __init__.py        #   编排器
│           ├── _http.py           #   GitHub API 拉取
│           ├── _lang.py           #   JSON 语言文件对齐
│           └── _guideme.py        #   GuideME 文档对齐
├── tests/
│   ├── fixtures/                 # 测试数据
│   ├── test_config.py
│   ├── test_database.py
│   ├── test_format_checker.py
│   ├── test_fuzzy_search.py
│   ├── test_key_alignment.py
│   ├── test_lang_parser.py
│   ├── test_lemma_merge.py
│   ├── test_phase4_filter.py
│   ├── test_pipeline_integration.py
│   ├── test_pr_guideme.py
│   ├── test_pr_lang.py
│   ├── test_report_generator.py
│   ├── test_terminology_builder.py
│   └── test_terminology_extract.py
├── .github/workflows/            # CI: pytest + pyright (Python 3.11-3.13)
└── output/                       # 输出目录
```

## 许可证

[BSD 3-Clause](./LICENSE)
