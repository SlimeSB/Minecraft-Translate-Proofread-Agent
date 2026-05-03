# Minecraft 模组翻译审校工具

将 Minecraft 模组 JSON 语言文件（`en_us.json` ↔ `zh_cn.json`）的审校流程从纯 LLM Agent 改造为**程序化自动检查 + LLM 启发式审校**的混合架构。90%+ 的检查由确定性规则完成，LLM 只处理需要语义判断的条目。

## 快速开始

```bash
# 1. 配置 .env
cp .env.example .env
# 编辑 .env，填入 API key

# 2. 干运行（预览统计，不调 LLM）
python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o output --dry-run

# 3. 仅自动检查（零 token 消耗）
python run.py --en en_us.json --zh zh_cn.json -o output --no-llm

# 4. 完整流水线
python run.py --en en_us.json --zh zh_cn.json -o output

# 5. 交互模式（逐条手动判定）
python run.py --en en_us.json --zh zh_cn.json -o output --interactive
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `REVIEW_OPENAI_API_KEY` | API key（OpenAI 兼容） | 无（必填） |
| `REVIEW_OPENAI_BASE_URL` | API 地址 | `https://api.deepseek.com` |
| `REVIEW_OPENAI_MODEL` | 模型名 | `deepseek-v4-flash` |

## 项目结构

```
run.py                           # CLI 入口
.env.example                     # 环境变量模板
.gitignore
src/
├── pipeline/
│   └── review_pipeline.py       # 主编排器，串联全部 Phase
├── tools/                       # 无状态工具脚本
│   ├── key_alignment.py         # 键对齐 en↔zh，输出 matched/missing/extra
│   ├── fuzzy_search.py          # 编辑距离模糊搜索，查翻译记忆
│   └── terminology_extract.py   # n-gram 高频词提取
├── checkers/                    # 全自动检查器
│   ├── format_checker.py        # 11 项格式验证（占位符/标签/标点/错字...）
│   └── terminology_builder.py   # 词形归并 + 术语表构建 + 一致性检查
├── llm/
│   └── llm_bridge.py            # LLM prompt 构建 + 响应解析 + 交互模式
└── reporting/
    └── report_generator.py      # 多来源 verdict 合并去重 + 报告生成
tests/
└── fixtures/
    ├── en_us.json               # 测试用英文语言文件
    └── zh_cn.json               # 测试用中文语言文件
```

## 流水线架构

```
Phase 1: 键对齐 ──→ alignment.json
    │                 {matched_entries, missing_zh, extra_zh, suspicious_untranslated}
    ▼
Phase 2: 术语提取 ──→ terminology_glossary.json
    │                 {术语表 + 翻译不一致列表}
    ▼
Phase 3a: 格式检查 ──→ format_verdicts.json
    │                 {占位符/标签/标点/错字/省略号/声音字幕/能量单位/按键...}
    ▼
Phase 3b: 模糊搜索 ──→ fuzzy_results.json (仅对 .desc / death.attack. / advancements.*)
    │
    ▼
Phase 3c: LLM 审校 ──→ llm_verdicts.json
    │                 筛选 ~39% 高价值条目（进度/死亡信息/魔咒/声音字幕/书籍/实体/长文本）
    │                 每批 20 条，带术语表 + 自动检查结果作为上下文
    ▼
Phase 4: 报告生成 ──→ review_report.json + zh_cn_annotated.json
```

## 判定体系

| 标记 | 含义 | 来源 |
|------|------|------|
| ❌ FAIL | 误译/漏译/格式错误/未翻译 | 自动检查 + LLM |
| ⚠️ SUGGEST | 风格/措辞改进建议 | 自动检查 + LLM |
| 🔶 REVIEW | 需人工判断的疑难 | LLM |
| PASS | 通过（不写入报告） | — |

**自动检查覆盖的规则：**
1. 占位符完整性（`%d/%s/%f/%n$s/%msg%/{0}` 等）
2. 特殊标签完整性（`§` 颜色码、`&` 格式码、`$(action)`、HTML 标签、`<br>`、`\n`）
3. tellraw JSON（仅翻译 `text` 键）
4. 中文标点规范（全角标点、半角 `[]`、中英文间距）
5. 省略号格式（禁用 `...`）
6. 能量/体积单位保留（FE、RF、MB）
7. 键盘按键保留（Shift、Ctrl 等）
8. 空翻译检测（`zh == en` 且非代码/专有名词）
9. 错别字检测（的/地/得、在/再、未/末 等 18 组）
10. 声音字幕格式（`主体：声音`）
11. 尾部空格功能冲突

## 关键决策

### 为什么只有 ~39% 条目发给 LLM？

- **纯界面/功能性条目**（容器名、按键名、配置项等）格式正确即可 PASS，无需 LLM 审校
- **自动检查无问题 + 短文本 + 非关键类别**的条目直接 PASS
- 仅以下类别强制送 LLM：进度、死亡信息、魔咒、声音字幕、书籍、实体、状态效果、药水、`.desc/.lore/.tooltip` 等描述性文本、>80 字符长文本

### 术语表如何工作？

1. `terminology_extract.py` 从 EN 提取 unigrams/bigrams/trigrams 及频次
2. `terminology_builder.py` 做词形归并（复数→单数、过去式→原形），按合并后频次 ≥3 构建术语表
3. 对只有一个翻译的"一致"术语，强制检查所有条目必须使用该译文
4. 对有多个翻译的"不一致"术语，列出供 LLM / 人工裁决

### Verdict 合并去重

同一 key 可能有多个 verdict（格式检查发现 + 术语检查发现 + LLM 发现），合并时取最高优先级：
- 优先级：FAIL > REVIEW > SUGGEST
- 同级别时 LLM 判断优先于自动判断
- 所有 reason 合并去重展示

## 输出文件

| 文件 | 说明 |
|------|------|
| `alignment.json` | 键对齐报告（Phase 1） |
| `terminology_glossary.json` | 术语表（Phase 2） |
| `format_verdicts.json` | 自动格式检查结果（Phase 3a） |
| `fuzzy_results.json` | 模糊搜索结果（Phase 3b） |
| `llm_verdicts.json` | LLM 审校结果（Phase 3c） |
| `review_report.json` | **最终审校报告**（合并所有来源） |
| `zh_cn_annotated.json` | 带注释的可读副本（仅 FAIL/REVIEW 条目含 `_comments` 段） |

## 开发

```bash
# 添加新格式检查
# 编辑 src/checkers/format_checker.py
# 在 FormatChecker.__init__ 中向 checks 列表追加新方法
# 方法签名: def _check_xxx(self, key, en, zh) -> dict | None

# 添加新术语归并规则
# 编辑 src/checkers/terminology_builder.py
# 在 IRREGULAR_PLURALS / IRREGULAR_VERBS 中追加映射

# 添加新键名分类
# 编辑 src/llm/llm_bridge.py
# 在 KEY_CATEGORY_RULES 或 LLM_REQUIRED_CATEGORIES 中追加
```
