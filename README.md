![DEEPSEEK](img/image-1.png)
> 本仓库完全由 **GitHub Copilot (DeepSeek-V4-Pro)** 辅助开发。

# Minecraft Mod Translation Proofread Agent

Minecraft 模组简中翻译自动化审校工具。对照原文审查译文，自动检测格式错误、术语不一致、语义偏差等问题，并生成结构化审校报告。

支持三种原文格式：**JSON** (`en_us.json`)、**Lang** (`en_us.lang`, `key=value`)、**GuideME** (`ae2guide/*.md`)。

## 特性

- **键对齐** — 自动匹配中英文键，检测缺失/多余/疑似未翻译条目
- **多格式支持** — JSON、Lang（`key=value`）、GuideME 文档全部覆盖
- **术语提取与词库构建** — N-gram 提取 + 词形归并（规则/模糊/LLM 三级）→ 自动构建术语表并一致性检查
- **程序化格式检查** — 10 项确定性检查（占位符、颜色码、tellraw JSON、标点规范等），零 LLM 成本
- **LLM 启发式审校** — 仅将歧义/语义问题提交 LLM，大幅降低 token 消耗
- **模糊搜索翻译记忆** — SQLite FTS5 + Levenshtein 发现相似原文的不同翻译
- **PR 模式** — 直接对 GitHub PR diff 做审校，支持 JSON/Lang/GuideME 三种文件类型
- **原版key碰撞检测** — 检测模组是否覆盖了 Minecraft 原版语言文件的 key
- **最终过滤** — Phase 5 再经 LLM 剔除误报，减少噪音

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

### 配置

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

# 仅重跑最终过滤
python run.py --filter-only -o ./output/
```

### 输出

所有文件输出到 `--output-dir`（默认 `./output/`）：

| 文件 | 说明 |
|------|------|
| `00_pr_alignment.json` | PR 模式原始对齐数据 |
| `01_alignment.json` | 键对齐结果 |
| `02_terminology_glossary.json` | 术语表 |
| `03_format_verdicts.json` | 格式检查 verdicts |
| `04_fuzzy_results.json` | 模糊搜索结果 |
| `05_llm_verdicts.json` | LLM 审校 verdicts |
| `06_review_report.json` | **最终审校报告** |
| `07_filter_discards.json` | 过滤驳回记录 |
| `zh_cn_annotated.json` | 带注释的可读版翻译文件 |

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
├── lemma_cache.json              # 词形缓存（持续学习）
├── data/
│   └── vanilla_keys.json         # 原版 key 列表（碰撞检测）
├── src/
│   ├── config.py                 # 配置加载器
│   ├── pipeline/
│   │   └── review_pipeline.py    # 主编排器（6 阶段流水线）
│   ├── checkers/
│   │   ├── format_checker.py     # 全自动格式验证
│   │   ├── terminology_builder.py# 术语提取 & 一致性检查
│   │   ├── lemma_merge.py        # 词形归并逻辑
│   │   └── lemma_cache.py        # 词形缓存
│   ├── llm/
│   │   └── llm_bridge.py         # LLM 桥接（prompt构建/批量审校/过滤）
│   ├── reporting/
│   │   └── report_generator.py   # 报告生成 & 合并
│   └── tools/
│       ├── key_alignment.py      # 键对齐 & 原版碰撞检测
│       ├── lang_parser.py        # .lang 文件解析器
│       ├── terminology_extract.py# N-gram 术语提取
│       ├── fuzzy_search.py       # SQLite FTS5 模糊搜索
│       ├── pr_aligner.py         # PR CLI 入口（兼容）
│       └── pr/                   # PR 对齐模块化架构
│           ├── __init__.py       #   编排器
│           ├── _http.py          #   GitHub API 拉取
│           ├── _lang.py          #   JSON 语言文件对齐
│           └── _guideme.py       #   GuideME 文档对齐
├── tests/
│   ├── fixtures/                 # 测试数据
│   ├── test_format_checker.py
│   ├── test_key_alignment.py
│   ├── test_fuzzy_search.py
│   ├── test_terminology_extract.py
│   ├── test_lemma_merge.py
│   └── test_lang_parser.py
└── output/                       # 输出目录
```

## 许可证

[BSD 3-Clause](./LICENSE)
