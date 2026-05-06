![DEEPSEEK](img/image-1.png)
> 本仓库完全由 **GitHub Copilot (DeepSeek-V4-Pro)** 辅助开发。

# Minecraft Mod Translation Proofread Agent

Minecraft 模组简中翻译自动化审校工具。对照 `en_us.json` 审查 `zh_cn.json`，自动检测格式错误、术语不一致、语义偏差等问题，并生成结构化审校报告。

## 特性

- **键对齐** — 自动匹配中英文键，检测缺失/多余/疑似未翻译条目
- **术语提取与词库构建** — N-gram 提取 + 词形归并（规则/模糊/LLM 三级）→ 自动构建术语表并一致性检查
- **程序化格式检查** — 10 项确定性检查（占位符、颜色码、tellraw JSON、标点规范等），零 LLM 成本
- **LLM 启发式审校** — 仅将歧义/语义问题提交 LLM，大幅降低 token 消耗
- **模糊搜索翻译记忆** — SQLite FTS5 + Levenshtein 发现相似原文的不同翻译
- **PR 模式** — 直接对 GitHub PR（CFPAOrg 模组翻译包）diff 做审校
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

编辑 `.env` 填入 API 密钥：

```
REVIEW_OPENAI_API_KEY=sk-your-key-here
REVIEW_OPENAI_BASE_URL=https://api.deepseek.com/
REVIEW_OPENAI_MODEL=deepseek-v4-flash
```

## 用法

```bash
# 完整审校（程序化 + LLM）
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/

# 仅自动检查（不调 LLM）
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --no-llm

# 干运行（只统计，不调 LLM）
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --dry-run

# 交互模式（逐条手动判定）
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --interactive

# PR 模式
python run.py --pr 1234 --repo CFPAOrg/Minecraft-Mod-Language-Package -o ./output/

# 仅重跑最终过滤
python run.py --filter-only -o ./output/
```

### 输出

所有文件输出到 `--output-dir`（默认 `./output/`）：

| 文件 | 说明 |
|------|------|
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

详见 [DEVELOPMENT.md](./DEVELOPMENT.md)。

## 项目结构

```
├── run.py                        # CLI 入口
├── review_config.json            # 审校配置
├── src/
│   ├── config.py                 # 配置加载器
│   ├── pipeline/                 # 主编排器
│   ├── checkers/                 # 格式检查 & 术语构建
│   ├── llm/                      # LLM 桥接
│   ├── reporting/                # 报告生成
│   └── tools/                    # 独立工具（键对齐、模糊搜索、PR 对齐）
├── tests/fixtures/               # 测试用例
└── output/                       # 输出目录
```

## 许可证

[BSD 3-Clause](./LICENSE)
