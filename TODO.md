# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

> 记录需要改进但未实施的工程问题。

## 当前待办

### 1. Windows 终端 GBK 编码问题
`src/cli.py:configure_utf8_output()` 已有 `isatty()` 检测重新配置 stdout 为 UTF-8，但 PowerShell 管道场景（`python run.py ... | tee output.log`）仍可能乱码。可增加 `--utf8` 参数或自动检测 PowerShell 环境（`WT_SESSION` 等环境变量）。

### 2. 原版 key 列表待完善
`data/vanilla_keys.json` 目前仅包含约 300 个示例 key（advancements/biomes/blocks部分），未涵盖全部原版 key。完整列表可从各版本 Minecraft 的 `en_us.json` 提取补全。

### 3. 添加 Pipeline 级别集成测试
当前测试覆盖各独立模块（79 tests），缺少端到端 Pipeline 级别测试。可在 `tests/` 下添加使用 `tests/fixtures/` 数据的 `--no-llm --dry-run` 完整流水线验证。

### 4. Config 从全局单例重构为可注入
当前 `src/config.py` 是模块级全局单例，各模块通过 `from src import config as cfg` 引用。已创建 `PipelineContext` 可携带配置，但 `llm/prompts.py` 和 `config.py` 底层仍硬编码全局引用。后续可将 Config 类注入 Phase 函数。
