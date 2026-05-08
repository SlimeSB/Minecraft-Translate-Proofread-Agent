# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

`python run.py --pr 5979 -o ./output/ --external-dict`

> 记录需要改进但未实施的工程问题。共 184 个单元测试（14 个模块），全部通过。

## 待办

### 5. PACKER-INFO.md 规范未实现（独立项目）
`PACKER-INFO.md`（315 行）描述了一个独立的 **Packer 工具**，将 `projects/assets/` 下模组翻译打包为 Minecraft 资源包 ZIP。包含四策略分发（direct/indirect/composition/singleton）、命名空间配置合并、字符/路径替换等复杂打包逻辑。建议作为独立仓库/分支实现。