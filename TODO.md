# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

> 记录需要改进但未实施的工程问题。共 184 个单元测试（14 个模块），全部通过。

## 待办

### 5. PACKER-INFO.md 规范未实现（独立项目）
`PACKER-INFO.md`（315 行）描述了一个独立的 **Packer 工具**，将 `projects/assets/` 下模组翻译打包为 Minecraft 资源包 ZIP。包含四策略分发（direct/indirect/composition/singleton）、命名空间配置合并、字符/路径替换等复杂打包逻辑。建议作为独立仓库/分支实现。

### 12. pr模式的术语逻辑
pr模式下不要只从diff生成术语，应当从pr内的，完整的en和zh文件生成术语，这样更严谨。
交给大模型校对的时候才只给diff的词条，这样可以减少劳动。

### 13. 术语表生成优化
程序自动生成的术语表有时候会有些问题，试试术语+1-5个包含术语的上下文交给llm判断并修改一次。用1个最长的+4个最短的原文。
有的术语是“使……能够”这样的带省略号的格式，实现起来似乎有些复杂先不弄了，但是这个问题记一下先。