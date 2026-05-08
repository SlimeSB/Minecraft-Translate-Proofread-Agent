# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

> 记录需要改进但未实施的工程问题。共 184 个单元测试（14 个模块），全部通过。

## 已完成 ✓

- ✅ Windows 终端 GBK 编码 — configure_utf8_output 已处理
- ✅ 原版 key 提取脚本 — scripts/extract_vanilla_keys.py
- ✅ Pipeline 级别集成测试 — tests/test_pipeline_integration.py (10 个测试)
- ✅ Config 可注入 — PipelineContext.config 字段
- ✅ src/__init__.py 版本信息 — __version__ = "2.0.0"
- ✅ 过滤缓存 hash 碰撞修复 — blake2b digest_size 8→16 (128-bit)
- ✅ 类型检查配置 — pyrightconfig.json
- ✅ 外部词典下载脚本 — scripts/download_external_dict.py
- ✅ CI/CD Pipeline — .github/workflows/test.yml (test + typecheck)
- ✅ 外部词典内存优化 — 按需 SQLite 查询替代全量加载 (~200MB→~10MB)

## 待办

### 5. PACKER-INFO.md 规范未实现（独立项目）
`PACKER-INFO.md`（315 行）描述了一个独立的 **Packer 工具**，将 `projects/assets/` 下模组翻译打包为 Minecraft 资源包 ZIP。包含四策略分发（direct/indirect/composition/singleton）、命名空间配置合并、字符/路径替换等复杂打包逻辑。建议作为独立仓库/分支实现。
