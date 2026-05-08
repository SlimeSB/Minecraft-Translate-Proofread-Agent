# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

> 记录需要改进但未实施的工程问题。共 174 个单元测试（13 个模块），全部通过。

## 当前待办

### 2. 原版 key 列表未填充
`data/vanilla_keys.json` 当前仅含 4 个元数据字段（`_note`, `_source`, `_version`, `keys`），`keys` 键值实际未填充任何原版 key，碰撞检测完全无效。需从各版本 Minecraft 的 `en_us.json` 提取完整列表补全。

### 3. 添加 Pipeline 级别集成测试
当前 174 个测试覆盖各独立模块，但缺少端到端流水线集成测试（且 Phase 3b/3c 无独立测试文件）。可在 `tests/` 下添加使用 `tests/fixtures/` 数据的 `--no-llm --dry-run` 完整流水线验证。

### 4. Config 从全局单例重构为可注入
`src/config.py` 是模块级全局单例（`_cfg_cache`），各模块通过 `from src import config as cfg` 引用。`PipelineContext` 已存在但未携带配置，`llm/prompts.py` 和多个 Phase 仍硬编码 `import config`。可将 Config 注入 Phase 函数或挂载到 `PipelineContext` 上。

### 5. PACKER-INFO.md 规范未实现
`PACKER-INFO.md`（315 行）描述了一个独立的 **Packer 工具**，将 `projects/assets/` 下模组翻译打包为 Minecraft 资源包 ZIP。非本项目已实现的代码，属于待移植/实现的组件规范。其中包含四策略分发（direct/indirect/composition/singleton）、命名空间配置合并、字符/路径替换等复杂打包逻辑。

### 6. 外部词典内存优化
`src/dictionary/external.py` 将 133.8MB SQLite 数据库（90 万条记录）全量加载到内存（约 200-300MB RAM），使用时只做简单 EN 单词匹配。可改为 SQLite 原地查询（FTS5 全文索引）按需检索，避免全量内存占用。

### 7. CI/CD Pipeline 缺失
无任何 CI 配置（GitHub Actions / GitLab CI），174 个测试仅靠手动运行。建议添加自动测试 + 最小 lint 检查。

### 8. 类型检查未配置
`src/models.py` 已全面 TypedDict 化且无 `Any`，但没有 mypy/pyright 配置文件或 CI 检查，类型安全仅靠约定。

### 9. 过滤缓存 hash 碰撞风险
`filter_cache.py` 的 `_cache_key()` 使用 `blake2b(digest_size=8)` 即 64-bit hash，字典记录数超 10^5 时生日悖论碰撞概率不可忽略。可增大 digest_size 到 16 或增加 SQLite 备用精确匹配校验。

### 10. 项目入口 `src/__init__.py` 为空
无 package-level 文档或版本信息，缺少 `__version__` 导出。

### 11. 外部词典需手动下载
`data/Dict-Sqlite.db`（133.8MB）需从外部仓库（i18n-Dict-Extender）单独下载，无自动化脚本或 submodule 管理，新用户容易遗漏。
