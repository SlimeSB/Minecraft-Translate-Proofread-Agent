# 审校工具 — Minecraft Mod Translate Review

Minecraft-Mod-Language-Package 审校流程的可视化桌面工具。支持自动扫描本地/远端审校产出，多维度筛选审校意见，管理术语表。

## 技术栈

- **框架**: React 19 + TypeScript
- **构建**: Vite 8
- **样式**: Tailwind CSS v4（无组件库依赖）
- **状态管理**: Zustand
- **桌面封装**: Electron 42
- **路由**: React Router 7

## 当前进度

### ✅ 已完成

| 模块 | 状态 | 说明 |
|------|------|------|
| 项目脚手架 | ✅ | Vite + React + TS + Tailwind |
| 类型定义 | ✅ | report/glossary/config/translator 全部 TypedDict |
| 状态管理 | ✅ | 4 个 Zustand store（report/glossary/config/pipeline） |
| 通用组件 | ✅ | Layout/Sidebar/FileDropzone/StatCard |
| **首页** | ✅ | 三级自动扫描 + 手动上传 + API 配置 + PR 输入 |
| **审校页面** | ✅ | 5 项统计卡片 + 四维筛选 + 可展开表格 |
| **术语页面** | ✅ | 搜索 + 停用词标记 + 导出 |
| **日志页面** | ✅ | Token 用量 + Phase 耗时 + 日志流（mock 数据） |
| **翻译预留** | ✅ | 引擎接口定义 + 占位页面 |
| **路由导航** | ✅ | 5 条路由 + 侧边栏高亮 |
| **Electron 封装** | ✅ | main.ts + preload.ts + IPC 文件扫描 |
| **自动扫描** | ✅ | Electron IPC / 后端 HTTP API / 无自动三级回退 |
| Spec 更新 | ✅ | design/proposal/tasks 均已完成 |

### ⏳ 待完成

| 任务 | 优先级 | 说明 |
|------|--------|------|
| 后端 FastAPI 服务 | 低 | 用于 PR 触发 + SSE 日志推送 |
| 虚拟滚动 | 低 | 处理 >10000 条 verdict 的大文件 |
| 筛选条件 URL 同步 | 低 | URL query string 与筛选状态双向同步 |
| 搜索高亮 | 低 | 搜索结果关键字高亮 |

## 启动方式

```bash
cd frontend
npm run dev              # 浏览器模式 → http://localhost:5173
npm run dev:electron     # 启动 Electron 桌面应用
npm run build            # 构建 renderer + electron
npm run dist             # 打包为安装包
```

## 扫描模式

前端启动后自动按以下优先级扫描文件：

1. **Electron 桌面模式** — 通过 `fs` 扫描 `output/`、cwd、父目录
2. **服务器模式** — 请求 `http://localhost:8000/api/scan-files`（需启动后端）
3. **纯浏览器模式** — 仅手动拖拽上传

手动上传始终可用，作为自动扫描的备用方式。

## 项目结构

```
frontend/
├── electron/
│   ├── main.ts            # Electron 主进程（IPC、窗口管理）
│   ├── preload.ts         # contextBridge 安全暴露 API
│   └── tsconfig.json
├── src/
│   ├── components/        # Layout, Sidebar, FileDropzone, StatCard
│   ├── hooks/             # useAutoScan
│   ├── pages/             # HomePage, ReviewPage, GlossaryPage, LogsPage, TranslatePage
│   ├── stores/            # Zustand stores (useReportStore, useGlossaryStore, ...)
│   ├── types/             # TypeScript 类型定义 + electron.d.ts
│   ├── App.tsx            # 路由配置
│   └── main.tsx           # 入口
├── index.html
├── vite.config.ts
└── package.json
```
