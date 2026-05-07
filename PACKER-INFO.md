现在我已读完所有源文件，下面是完整的 Packer 逻辑描述：

---

# Packer 完整逻辑描述

## 一、整体目标

将 assets 下各模组的翻译文件打包成一个 Minecraft 资源包 ZIP 文件。输出文件名 `Minecraft-Mod-Language-Modpack-{version}.zip`，同时生成 `{version}.md5` 校验文件。

## 二、入口与参数

**命令行参数**：
- `version`（必选）：Minecraft 版本号，如 `1.20`、`1.16`
- `--increment`（可选布尔标志）：增量打包模式

---

## 三、执行流程

### 步骤 1：加载全局配置

从 `./config/packer/{version}.json` 读取 JSON 配置，字段名 camelCase。

**配置结构** (Config)：

```python
Config = {
    "base": BaseConfig,       # 版本级唯一配置
    "floating": FloatingConfig  # 可与命名空间下级 local-config 合并的浮动配置
}
```

**BaseConfig 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | string | 打包目标版本号 |
| `targetLanguages` | string[] | 目标语言列表，如 `["zh_cn"]`，用于文件筛选 |
| `mcMetaTemplate` | string | `pack.mcmeta` 模板文件路径 |
| `mcMetaParameters` | object[] | `pack.mcmeta` 的 string.Format 参数 |
| `readmeTemplate` | string | `README.txt` 模板文件路径 |
| `readmeParameters` | object[] | `README.txt` 的 string.Format 参数 |
| `exclusionMods` | string[] | 排除的模组 ID 列表（暂未直接使用于文件筛选） |
| `exclusionNamespaces` | string[] | 排除的命名空间列表 |

**FloatingConfig 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `inclusionDomains` | string[] | 强制包含的 domain（如 `font`、`textures`、`gui`） |
| `exclusionDomains` | string[] | 强制排除的 domain |
| `exclusionPaths` | string[] | 强制排除的文件相对路径（如 packer-policy.json） |
| `inclusionPaths` | string[] | 强制包含的文件相对路径 |
| `characterReplacement` | dict[str,str] | 文件内容的**正则**替换表（key 是正则模式，value 是替换文本） |
| `destinationReplacement` | dict[str,str] | 目标路径的**正则**替换表 |

---

### 步骤 2：增量模式（可选）

若 `--increment` 为 true，使用 Git 对比当前 HEAD 与 `origin/main`：

1. 获取所有变更文件的路径（新增+删除+修改，即 `TreeChanges`）
2. 对每个变更文件路径，检查是否匹配模式 `projects/assets/<mod_id>/<version>/...`（路径分割后第0段=`projects`，第1段=`assets`，第3段=`version`）
3. 提取第2段作为 **mod_id**
4. 返回去重后的 mod_id 集合

结果：仅打包这些 mod，若为空则全部打包。

---

### 步骤 3：核心查询管线（最复杂部分）

#### 3.1 枚举模组目录

遍历 assets 下所有子目录，每子目录名即为 `mod_id`。

如果在增量模式下，只保留 `mod_id` 在变更集合中的那些。

#### 3.2 定位版本目录

在每个 mod 目录下查找名为 `version`（来自配置）的子目录。不存在则跳过。

#### 3.3 枚举命名空间

在版本目录下枚举所有子目录，每子目录名即为 `namespace`。

**过滤规则**：
1. `namespace` 不在 `BaseConfig.exclusionNamespaces` 中
2. `namespace` 符合命名规范：正则 `^[a-z0-9_.-]+$`（仅小写字母、数字、`_`、`.`、`-`）

#### 3.4 加载命名空间配置

在命名空间目录中查找两个文件（均为可选）：

**① packer-policy.json** — 打包策略列表：

```json
[
    {
        "type": "direct",           // 策略类型
        // 额外参数（取决于type）：
        "source": "...",
        "destType": "json",
        "relativePath": "...",
        "modifyOnly": true,
        "append": false
    }
]
```

策略类型枚举：
- `direct` — 从当前目录直接加载文件（**默认**，无此文件时使用）
- `indirect` — 从其他目录加载并重写命名空间
- `composition` — 从组合模板生成语言文件
- `singleton` — 加载单个指定文件

若无此文件，默认策略为 `[{"type": "direct"}]`。

**② local-config.json** — 局域浮动配置（`FloatingConfig` 结构）。

若存在，调用 `Config.Modify(localConfig)` 合并：将局域配置的各列表字段与全局配置**拼接去重**；字典字段（`characterReplacement`、`destinationReplacement`）以 key 去重合并（局域覆盖全局）。

#### 3.5 四种策略的执行逻辑

##### 策略 A：Direct（直接加载）

1. 递归遍历命名空间下所有文件
2. 计算 `relativePath` = 文件相对于命名空间目录的路径（如 `lang/zh_cn.json`），将 `\` 归一化为 `/`
3. 计算 `destination` = `assets/<namespace>/<relativePath>`

**文件筛选顺序**（短路逻辑）：
- **排除**：`relativePath` 在 `exclusionPaths` 中 → 跳过
- **包含**：`relativePath` 在 `inclusionPaths` 中 → 通过
- **包含**：`relativePath` 的 domain（第一段路径如 `font`）在 `inclusionDomains` 中 → 通过
- **包含**：`destination` 包含 `targetLanguages` 中的任一项（如含有 `zh_cn`）→ 通过
- **排除**：`relativePath` 的 domain 在 `exclusionDomains` 中 → 跳过
- 其余：跳过

**Provider 创建**（根据文件类型）：

| 条件 | Provider 类型 | 说明 |
|------|-------------|------|
| 父目录为 `lang` 且扩展名 `.json` | `TermMappingProvider<JsonNode>` | JSON 语言文件（现代 MC） |
| 父目录为 `lang` 且扩展名 `.lang` | `TermMappingProvider<string>` | `.lang` 语言文件（旧版 MC） |
| 扩展名 `.txt` `.json` `.md` | `TextFile` | 普通文本文件 |
| 其他 | `RawFile` | 二进制原样复制 |

**ApplyOptions**（来自策略参数的 `modifyOnly` 和 `append`，默认均为 false）：

| 参数 | 类型 | 作用于 |
|------|------|--------|
| `modifyOnly` | bool | TermMappingProvider 合并时仅更新已有 key，不新增 |
| `append` | bool | TextFile 合并时拼接而非覆盖 |

##### 策略 B：Indirect（间接引用）

1. 从 `source` 参数获取重定向目录路径
2. 对重定向目录**递归调用** `EnumerateRawProviders`（即递归应用其自己的策略）
3. 对返回的每个 provider：用正则替换其 `destination` 中的命名空间部分：`(?<=^assets/)[^/]*(?=/)` → 当前命名空间名

用途：多个 mod 共享同一套翻译文件时，一个命名空间引用另一个。

##### 策略 C：Composition（组合生成）

1. 从 `source` 参数获取组合文件路径
2. 从 `destType` 参数获取输出类型（`"lang"` 或 `"json"`）

**组合文件格式**：
```json
{
    "target": "assets/<namespace>/lang/zh_cn.json",
    "entries": [
        {
            "templates": {
                "block.{0}_{1}": "{0}的{1}",
                "item.{0}_{1}": "{0}制成的{1}"
            },
            "parameters": [
                { "0": "stone", "1": "砖块" },
                { "0": "wood", "1": "木板" }
            ]
        }
    ]
}
```

**生成逻辑**：
- 对每个 entry：
  1. `CrossMap(parameters)`：对所有参数对象做**笛卡尔积**
     - 例如 2 个参数对象 × 2 个参数对象 = 4 个组合
  2. 对每个参数组合 × 每个模板：
     - `formattedKey = string.Format(template.key, param组合.key序列)`
     - `formattedValue = string.Format(template.value, param组合.value序列)`
  3. 按 key 去重（`DistinctBy`），保留第一个
- 输出为 `TermMappingProvider`，destination = `target`

##### 策略 D：Singleton（单文件加载）

1. 从 `source` 参数获取文件路径
2. 从 `relativePath` 参数获取相对路径
3. destination = `assets/<namespace>/<relativePath>`
4. 创建对应的 Provider（根据扩展名判断类型）

#### 3.6 同目标文件合并

所有 Provider 按 `destination` 分组。同组内使用 `Aggregate` 合并：

**合并规则** (`ApplyTo`)：

| Provider 类型 | 行为 |
|-------------|------|
| `TermMappingProvider` | 合并字典。若 `modifyOnly=true`：仅更新基础映射中**已存在**的 key；否则 `TryAdd`（新 key 加入，不覆盖已有值） |
| `TextFile` | 若 `append=true`：文本以换行符拼接；否则保持基础文本不变 |
| `RawFile` | 保持基础文件不变（不合并） |

#### 3.7 字符替换

对每个 provider，依次应用 `characterReplacement` 中的所有正则替换：
- key = 正则模式（如 `\\[\\[钅卢\\]\\]`），value = 替换文本（如 Unicode 私用区字符）
- 仅对文本内容生效（`TermMappingProvider` 替换所有值中的匹配，`TextFile` 替换全文，`RawFile` 不变）

#### 3.8 目标路径替换

对每个 provider，依次应用 `destinationReplacement` 中的正则替换到 `destination` 路径上。

---

### 步骤 4：构建初始文件

固定加入以下 4 个文件：

| 文件 | 来源 | 说明 |
|------|------|------|
| `pack.png` | pack.png | 资源包图标，RawFile 直接复制 |
| LICENSE | LICENSE | 许可证，TextFile 读取文本 |
| `README.txt` | 模板文件（配置的 `readmeTemplate`） | 用 `readmeParameters` 做 `string.Format` |
| `pack.mcmeta` | 模板文件（配置的 `mcMetaTemplate`） | 写入时追加 `DateTime.UtcNow + 8小时` 作为首个参数，然后 `mcMetaParameters` |

---

### 步骤 5：写入 ZIP

1. 创建文件流 → `./Minecraft-Mod-Language-Modpack-{version}.zip`
2. 创建 `ZipArchive`（Update 模式，保持流打开）
3. **并行**写入所有 Provider（查询结果 + 初始文件共 4 个）
4. 每个 Provider 写入前检查 ZIP 内是否已有同名条目（有则抛异常）

**各 Provider 写入方式**：

| Provider | 写入方式 |
|----------|---------|
| `RawFile` | 源文件流 → ZIP entry 流（CopyTo） |
| `TextFile` | UTF-8 无 BOM StreamWriter → 写 `Content` 字符串 |
| `TermMappingProvider<string>` (.lang) | `key=value\n` 格式，逐行拼接 |
| `TermMappingProvider<JsonNode>` (JSON) | `JsonSerializer.Serialize`，`UnsafeRelaxedJsonEscaping`（不转义 Unicode），缩进输出 |
| `McMetaProvider` | 先用 `string.Format(Content, UTC+8时间)` 替换模板中的 `{0}`，再 UTF-8 写入 |

---

### 步骤 6：生成 MD5

1. 将文件流 `Seek(0)` 回到开头
2. 对整个 ZIP 内容计算 MD5
3. 写入 `./{version}.md5`（如 1.20.md5）

---

## 四、.lang 文件解析规则（Legacy 格式）

适用于 `key=value` 格式的旧版语言文件：

```
#PARSE_ESCAPES
tile.name=方块名称
item.sword=剑 \
  续行内容
```

- 跳过：空行、纯空白行
- 跳过：`//` `#` 开头的注释行
- 跳过：`/* */` 多行注释块
- 跳过：单独一行的 `{` 或 `}`
- 跳过：不含 `=` 的行
- 以第一个 `=` 分割 key 和 value
- `#PARSE_ESCAPES` 指令：启用转义处理
  - 行尾 `\` 表示续行：去掉 `\`，拼接下一行（去除前导空白）
- `TryAdd`：key 已存在时保留原值

---

## 五、目录结构总结

```
.
├── config/packer/{version}.json          ← 全局配置
├── projects/
│   ├── assets/
│   │   └── {mod_id}/                     ← 模组目录
│   │       └── {version}/                ← 版本目录
│   │           └── {namespace}/           ← 命名空间目录
│   │               ├── packer-policy.json ← 策略文件（可选）
│   │               ├── local-config.json  ← 局域配置（可选）
│   │               ├── lang/zh_cn.json    ← 语言文件
│   │               ├── lang/zh_cn.lang
│   │               └── textures/...       ← 资源文件
│   └── templates/
│       ├── pack.png
│       ├── LICENSE
│       ├── README.txt
│       └── pre_1_20_1_pack.mcmeta
└── Minecraft-Mod-Language-Modpack-{version}.zip  ← 输出
```

这就是完整的 Packer 逻辑，可以直接用 Python 复刻。核心复杂度在四种策略的分发、合并规则、以及 `.lang` 文件解析上。