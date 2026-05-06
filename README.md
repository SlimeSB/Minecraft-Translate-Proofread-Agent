![DEEPSEEK](img/image-1.png)
> 本仓库完全由 **GitHub Copilot (DeepSeek-V4-Pro)** 辅助开发。

# Minecraft 模组翻译审校工具

> 程序化自动检查 + LLM 启发式审校的混合架构。90%+ 检查由确定性规则完成，LLM 仅处理需要语义判断的条目。

## 快速开始

### 传统模式（本地文件）
```bash
# 1. 配置 LLM（可选）
cp .env.example .env          # 填入 API key

# 2. 运行
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --dry-run         # 干运行：显示统计，不调 LLM
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --no-llm          # 仅程序检查，零 token
python run.py --en en_us.json --zh zh_cn.json -o ./output/                   # 完整流水线
python run.py --en en_us.json --zh zh_cn.json -o ./output/ --interactive     # 交互模式：逐条手动判定
```

> 可直接使用仓库内置测试数据体验：  
> `python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/ --dry-run`

### PR 模式（GitHub Pull Request）
```bash
# 自动拉取 PR 差异并审校
python run.py --pr 1234 --repo CFPAOrg/Minecraft-Mod-Language-Package -o ./output/

# 使用已保存的 PR 对齐数据（跳过 GitHub 拉取）
python run.py --pr-alignment ./output/00_pr_alignment.json -o ./output/
```

### CLI 参数

| 参数 | 说明 | 默认值 |
| ---- | ---- | ------ |
| `--en` | en_us.json 路径（传统模式必需） | — |
| `--zh` | zh_cn.json 路径（传统模式必需） | — |
| `-o / --output-dir` | 输出目录 | `./output` |
| `--pr` | PR 编号（PR 模式） | — |
| `--repo` | GitHub 仓库名，如 `CFPAOrg/Minecraft-Mod-Language-Package` | — |
| `--token` | GitHub Token（可选，公共仓库限流 60 req/hr） | `""` |
| `--pr-alignment` | 已保存的 PR 对齐 JSON 文件路径 | — |
| `--no-llm` | 跳过 LLM 审校 | 关闭 |
| `--interactive` | 交互模式：逐条手动判定 | 关闭 |
| `--dry-run` | 干运行：显示统计，不调 LLM | 关闭 |
| `--min-term-freq` | 术语最低频次阈值 | `3` |
| `--fuzzy-threshold` | 模糊搜索相似度阈值 | `60.0` |
| `--batch-size` | LLM 每批条目数 | `20` |

> 参数互斥：要么提供 `--en --zh`（传统模式），要么提供 `--pr --repo` 或 `--pr-alignment`（PR 模式）。

## 环境变量

|           变量           |        说明         |           默认值           |
| ------------------------ | ------------------- | -------------------------- |
| `REVIEW_OPENAI_API_KEY`  | OpenAI 兼容 API key | 无（未设置则跳过 LLM）     |
| `REVIEW_OPENAI_BASE_URL` | API 地址            | `https://api.deepseek.com` |
| `REVIEW_OPENAI_MODEL`    | 模型名              | `deepseek-v4-flash`        |

## 流水线

```
  ┌──────────────────┐
  │ PR Mode (可选)    │  --pr --repo 或 --pr-alignment
  │ 00_pr_alignment  │  拉取 PR 差异，对齐 4-way 文件
  └────────┬─────────┘
           │ (PR 模式跳过传统 Phase 1 键对齐)
           ▼
  ┌───▼──────────┐
  │ Phase 1       │  键对齐 (en↔zh)
  │ 01_alignment  │
  ├───────────────┤
  │ Phase 2       │  术语提取 → 词形归并 → 术语表构建
  │ 02_glossary   │  (n-gram + 缓存学习 + 模糊聚类)
  ├───────────────┤
  │ Phase 3a      │  10 项格式检查（全程序化）
  │ 03_format     │  PR 模式注入原文变更但翻译未变更的 warning
  ├───────────────┤
  │ Phase 3b      │  模糊搜索 (SQLite FTS5)
  │ 04_fuzzy      │
  ├───────────────┤
  │ Phase 3c      │  LLM 审校（仅需要语义判断的条目）
  │ 05_llm        │  PR 模式分离 ZH-only 变更走特殊 prompt
  ├───────────────┤
  │ Phase 4       │  合并 verdicts → 审校报告
  │ 06_report     │
  ├───────────────┤
  │ Phase 5       │  LLM 最终过滤：筛除误报 → 更新报告
  │ 07_discards   │  保留驳回记录
  └───────────────┘
```

## 自动检查规则（10 项，全部程序化）

|  #  |      规则      |                         说明                         |
| --- | -------------- | ---------------------------------------------------- |
| 1   | 占位符完整性   | `%d/%s/%f/%n$s/%msg%/{0}` 等，`%1$s`↔`%s` 归一化比对 |
| 2   | 特殊标签完整性 | `§` / `&` / `$(action)` / HTML / `<br>` / `\n`       |
| 3   | tellraw JSON   | 仅翻译 `text` 键，其余键保留                         |
| 4   | 中文标点规范   | 全角标点、半角 `[]`、中英文间距                      |
| 5   | 省略号格式     | 禁用半角 `...`，须用 `……`                            |
| 6   | 单位保留       | FE、RF、MB 等能量/体积单位                           |
| 7   | 键盘按键保留   | Shift、Ctrl 等                                       |
| 8   | 空翻译检测     | `zh==en` 且非代码/专有名词                           |
| 9   | 声音字幕格式   | 须为 `主体：声音`（全角冒号）                        |
| 10  | 尾部空格冲突   | 尾部空格可能改变含义                                 |

> 错别字检测、语气/文化引用判断等语义级检查交给 LLM。

## LLM 审校策略 (Phase 3c)

- 按 key 前缀分组（`advancements.` / `death.` / `enchantment.` / `subtitles.` / `sound.` / `container.` / `key.` / `book.` / `item.` / `block.` / `entity.` / `effect.` / `potion.` / `biome.` / `commands.` / `chat.` 等），每组专属审查重点
- 未匹配前缀的条目归入 `__default__`，使用默认 prompt
- 术语表作为强制参考注入 prompt
- 并行 workers（默认 8），429 自动指数退避重试
- 动态检测键盘按键 / 鼠标操作，自动注入补充审校指南

**LLM 自动豁免**（同时满足以下全部条件的条目不调 LLM）：
1. 不属于强制 LLM 类别（进度/死亡/魔咒/声音字幕/声音/书籍/实体/状态效果/药水）
2. 键名不含 `.desc/.title/.lore/.tooltip/.flavor/.info/.message/.text`
3. EN ≤ 80 字符
4. 无自动检查问题

## 最终过滤 (Phase 5)

在 Phase 4 汇总所有 verdict 后，再次调用 LLM 审视完整的审校报告，筛除误报：

- 驳回值相同但无需翻译的条目（代码/占位符/数字）
- 驳回术语不一致但上下文合理的情况（如 `Tag View Cell` 中的 tag 不是"标签标准发信器"）
- 驳回标点/空格等对玩家体验无影响的微调建议
- 仅保留真正的翻译错误（漏译、误译、语气不匹配）
- 驳回记录保存至 `07_filter_discards.json`

## 术语表 (Phase 2)

纯程序化，不调 LLM 做翻译：
1. 从 EN 提取 unigrams / bigrams / trigrams，停用词过滤
2. 原始词面分桶 → LemmaCache 查表归并（跨次运行持续学习）→ 模糊聚类
3. 按频次 ≥ 5 + 共识 ≥ 60% 构建术语表（仅从事物名称条目取中文，描述性条目排除）
4. `\b` 词边界匹配检查一致性，标记不一致条目

> 缓存 `lemma_cache.json` 在每次 LLM 裁决后写入，跨次运行复用。

## 配置

所有可调参数与 prompt 模板集中在 [review_config.json](review_config.json)，修改此文件即可调整：
- 各 key 前缀分组的审查重点 / 风格参考 / 普适原则
- 术语阈值 / 聚类参数 / 停用词
- key 前缀分组与 LLM 必选类别
- 键盘按键 / 鼠标操作补充审校指南
- LLM 并行 worker 数（默认 8）

`src/config.py` 启动时校验所有配置键，未知键输出 stderr 警告。

## 项目结构

```
run.py                              # CLI 入口
review_config.json                  # 配置中心（prompt、阈值、停用词）
.env.example                        # 环境变量模板
translation-reviewer.agent.md       # VS Code Copilot 审校助手 agent
.gitignore
src/
├── config.py                       # 配置加载（全仓唯一配置来源）
├── pipeline/
│   └── review_pipeline.py          # 主编排器 Phase 1→4
├── tools/                           # 无状态工具
│   ├── key_alignment.py            # 键对齐 en↔zh
│   ├── fuzzy_search.py             # SQLite FTS5 模糊搜索
│   ├── terminology_extract.py      # n-gram 高频词提取
│   └── pr_aligner.py               # 🆕 PR 差异对齐器（GitHub API）
├── checkers/                       # 全自动检查器
│   ├── format_checker.py           # 10 项格式验证
│   ├── terminology_builder.py      # 词形分桶 + 缓存归并 + 术语表
│   ├── lemma_cache.py              # 词形缓存（跨次学习）
│   └── lemma_merge.py              # 词形归并逻辑
├── llm/
│   └── llm_bridge.py               # LLM prompt 构建 + 并行调用 + 重试
└── reporting/
    └── report_generator.py         # verdict 合并 + 报告生成
tests/
└── fixtures/
    ├── en_us.json                  # 测试英文源
    └── zh_cn.json                  # 测试中文译文
```

`src/config.py` 是代码侧加载入口，`terminology_builder.py`、`llm_bridge.py` 统一从此读取。

## 输出文件

|              文件              |                   说明                   |
| ------------------------------ | ---------------------------------------- |
| `00_pr_alignment.json`         | 🆕 PR 对齐数据（PR 模式独有）           |
| `01_alignment.json`            | 键对齐                                   |
| `02_terminology_glossary.json` | 纯程序术语表 `[{en, zh}]`                |
| `03_format_verdicts.json`      | 自动格式检查（PR 模式含注入警告）         |
| `04_fuzzy_results.json`        | FTS5 模糊搜索结果                        |
| `05_llm_verdicts.json`         | LLM 审校结果（含 ZH-only 变更）          |
| `06_review_report.json`        | 最终审校报告（合并去重，经 Phase 5 过滤） |
| `07_filter_discards.json`      | LLM 最终过滤驳回记录                    |
| `logs/latest.log`              | LLM prompt/response 日志（自动滚动存档） |
| `lemma_cache.json`             | 词形映射缓存（跨次复用）                 |

## 配置与数据文件

|              文件               |                        说明                        |
| ------------------------------- | -------------------------------------------------- |
| `review_config.json`            | 所有可调参数 + 全部 prompt 模板 + 术语停用词       |
| `translation-reviewer.agent.md` | VS Code Copilot agent 定义，用于在编辑器中直接审校 |
| `.env`                          | API key（不提交）                                  |
| `.env.example`                  | 环境变量模板                                       |
| `lemma_cache.json`              | 词形映射缓存（跨次复用）                           |
