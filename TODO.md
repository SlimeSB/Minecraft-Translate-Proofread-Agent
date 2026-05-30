# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

`python run.py --pr 5979 -o ./output/ --no-external-dict`

> 362 个单元测试（21 个模块），全部通过。

---

## 目前待办

- [ ] `test_database.py:190-220` — 4 个旧表不存在测试使用裸 `except Exception: pass`，应收窄为 `sqlite3.OperationalError`
- [ ] 架构：Vite + React 前端，调用 FastAPI 接口。后端 `run_in_executor` 独立线程池隔离 pipeline 执行。见 `openspec/changes/review-frontend/`
- [ ] **双词典注入 prompt 膨胀（原 Issue #4）** — 每条条目同时对 `ExternalDictStore` + `MinecraftDictStore` 调用 `lookup()`，每 batch ~75 tokens 开销。与 @anomaly 另有安排，暂不动。
- [ ] **`minecraft_dict.py` 未接入管线（331 行）** — `MinecraftDictStore` 仅被 `scripts/migrate_minecraft_db.py` 和测试引用，管线实际使用 `VanillaTermsStore`。功能与 `vanilla_terms.py` 重叠，待双词典方案确定后决定合并或接入。
- [ ] **`_format_rows()` 复杂度（原 Issue #5）** — `minecraft_dict.py:114-231` 约 65 行 6 层嵌套逻辑，longest/shortest/sensitive 选择 + reserved slots。有充分测试覆盖，重构风险可控但暂缓。
- [ ] feat: 帕秋莉手册支持
- [ ] feat: 组合文件和packer-policy支持。
- [ ] agent启发式对齐器
- [ ] 精简db

## 未计划

- [ ] 喂给 llm mod介绍等相关信息，源码等，实现理解风格、代码逻辑、游戏内表现等问题。
- [ ] 先理解、再翻译/校对
- [ ] 逐步启用 pyright 关键检查项（当前关闭 13 项：`reportAssignmentType`, `reportReturnType`, `reportAttributeAccessIssue`, `reportOptionalMemberAccess` 等；✅ `reportArgumentType` 已修）（工程太大，延期）
- [ ] `storage/database.py`: 从 `Mapping[str, Any]` 迁移到 TypedDict（SQLite 行数据形状多变，建议从简单边界开始）（工程太大，延期）
- [ ] **引入 jieba 分词增强 `_extract_common_zh`** — 将字级别子串匹配升级为 token 级别共享检测，解决公共中文词汇出现在不同位置时无法提取的问题（如 "铁锭"/"铜锭" 的公共 token "锭"）。需评估：jieba 默认词典对 Minecraft 材质词的切分准确度、自定义词典维护成本。

### 测试

- [ ] Phase 4 过滤器缺测试（仅 33 行，是审查管线最后关卡）— 需 mock LLM 响应 + DB 事务，现有测试框架对 pipeline 集成测试支持有限
- [ ] `external.py`（外部词典，153 行）零单元测试 — 依赖 SQLite 外部数据文件，需准备测试夹具

### 架构

- [ ] 消除 `asyncio.run()` 反模式（`bridge.py` 同步方法内调 async，无法在已有事件循环中复用）— 波及 LLMBridge 全部公有方法 + 所有 Phase 调用方，改后需全量回归。**评估：当前纯同步入口不触发嵌套，计划中，暂不动。**
- [ ] LLM 并发改用真异步 IO（当前通过线程池包装，非真异步）— 当前 threading + semaphore 虽非真异步但工作稳定，重构收益不确定
- [ ] Config 从全局单例重构为可注入 — `config.py` 是模块级全局单例，`llm/prompts.py` 等 15 个文件硬编码 `from src import config as cfg`。后续可将 Config 类注入 Phase 函数，改善测试隔离性。（工程大，延期）
- [ ] `PipelineContext` 拆分 — 26 个字段含 11 个 PR 专用字段，建议拆为 `PipelineInput`/`RuntimeConfig`/`PhaseResults` 子对象。涉及所有 Phase 签名变动，投入产出比当前不够，延期。
- [ ] Phase 3b 注册为正式 Phase — `phase3b_fuzzy.py` 当前作为 Phase 3c 子程序调用，独立注册无意义（模糊搜索就是为 LLM 审校服务的前置步骤）。**伪问题，不执行。**

## 已完成

- [x] 社区词典下载检查一下
- [x] Windows 终端 GBK 编码问题 — `safe_print()` 增加 buffer.write fallback；`run.py` 全部 `print()` 替换为 `safe_print()`。
- [x] 原版 key 列表：从 JSON 迁移到 SQLite（`data/Minecraft.db`，11618 条），`check_vanilla_collisions()` 通过运行时查询检测碰撞
- [x] Pipeline 级别集成测试：`tests/test_pipeline_integration.py`（10 个测试方法，134 行），`--no-llm` 模式 CI 安全
- [x] `terminology_extract.py:23` — 导入风格已统一为绝对导入
- [x] `phase3c_review.py:28` — `run_phase3c()` 拆为 `_filter_and_prepare()` + `_review_entries()` + 薄编排（11 行）
- [x] `_is_useful_term` / `_is_valid_term` 词法 check 逻辑重复 → 合并为 `src/tools/term_validation.py`
- [x] `openspec/specs/` 6 个已实现 spec 归档 + typeddict-migration change 归档
- [x] `models.py:104` — AlignmentDict total=False 修复
- [x] `database.py:115` / `key_alignment.py:40` — TypedDict 类型标注
- [x] 清理 3 处 `if __name__ == "__main__"` + argparse 死代码
- [x] 合并 `load_json()` → 保留 `fuzzy_search.py` 单副本
- [x] 合并 GBK-safe print → `report_generator.py` 从 `cli.py` 导入
- [x] `format_checker.py:93` — 内联 import 提至文件顶
- [x] `client.py` — `call_count` 改用 `nonlocal`，消除闭包可变状态
- [x] 消除死代码：`ALL_VERDICTS`、3 个 CLI `main()`
- [x] `term_validation.py` — except ImportError 加 stderr 警告
- [x] `ae2guide:` 硬编码 → `config.GUIDEME_PREFIX`
- [x] `phase4_filter.py:71` — `uncached_pass` → `pass_keys`
- [x] `client.py:59` — 日期格式加分隔符
- [x] `phase3c_review.py:104` — 确认 `total_chars` 非死赋值（两处均被使用）
- [x] `phase5_report.py:78` — 确认 `PipelineContext` 无 `issues` 字段，无变量遮盖

## 已放弃

- [x] `shutil.rmtree()` 清空 output 目录（`pipeline.py:67`）— 设计如此，勿在 `-o` 目录放其他文件即可
- [x] 合并两套 LLM JSON 解析器（`bridge.py` 和 `terminology_builder.py`）— 解析目标不同（审校 verdicts vs 术语修正），强行合并反增复杂度
- [x] `src/tools/pr/` 模块 TypedDict 迁移 — 跨三阶段、数据类型复杂，收益不及风险
- [x] `global` 散落 4 处 — 每处都有注释说明"设计如此"，改成 class 只是把 `global` 换成 `self.`，无实质改善
- [x] `_write_pr_output()` 10 参数 — 仅有 1 个调用方的 pure 输出函数，10 个参数避免隐式依赖，改 dataclass 反而多跳转一层
- [x] `extract_terms()` 107 行 — 纯函数、流程线性（tokenize → unigram → bigram → trigram → 组装），拆分打断阅读流
- [x] `create_openai_llm_call()` 93 行 — 闭包工厂模式，外层配置 + 内层 call() 逻辑紧凑，拆分意义不大

