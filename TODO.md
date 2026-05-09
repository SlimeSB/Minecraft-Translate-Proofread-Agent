# 待办与优化项

快速运行：`python run.py --en tests/fixtures/en_us.json --zh tests/fixtures/zh_cn.json -o ./output/`

`python run.py --pr 5979 -o ./output/ --external-dict`

> 291 个单元测试（18 个模块），全部通过。

---

### 类型系统被绕过（大重构）
- 10+ 文件用 `dict[str, Any]` 而非 TypedDict（`VerdictDict` 等形同虚设）
- **pyright 关闭 13 项核心检查** (`pyrightconfig.json`): `reportAssignmentType`, `reportReturnType`, `reportAttributeAccessIssue`, `reportOptionalMemberAccess` 等。`reportArgumentType` ✅ 已修。TypedDict 约束形同虚设。
- **目标**: 逐步启用关键检查项，清理类型标注


3. 代码重复

两套几乎一样的 LLM JSON 解析器（bridge.py 和 terminology_builder.py）
多个文件重复的 if __name__ == "__main__" + argparse 样板代码
4. asyncio.run() 反模式

bridge.py 在同步方法里调用 asyncio.run()，无法在已有事件循环中复用
LLM 并发的"异步"实际是通过线程池包装的，不是真异步 IO
5. Phase 4 过滤器严重缺测试

仅 33 行测试代码，是审查管线的最后关卡（决定哪些问题进报告）
external.py（外部词典，153 行）零单元测试
6. 闭包可变状态

client.py 用 call_count = [0]、usage = {} 这种闭包可变对象来追踪调用计数，脆弱且不可重入

---

## 已完成

| 项目 | 说明 |
|------|------|
| `_is_useful_term` / `_is_valid_term` 词法 check 逻辑重复 | 合并为 `src/tools/term_validation.py`，统一停用词来源，四处调用点统一 |

## 已丢弃（无需处理）

| 项目 | 原因 |
|------|------|
| `shutil.rmtree()` 清空 output 目录 (`pipeline.py:67`) | 设计如此，勿在 `-o` 目录放其他文件即可 |
