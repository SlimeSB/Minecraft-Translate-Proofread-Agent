import { app, BrowserWindow, ipcMain } from "electron";
import * as path from "path";
import * as fs from "fs";

let mainWindow: BrowserWindow | null = null;

const SCAN_TARGETS = [
  { file: "report.json", type: "report" as const },
  { file: "glossary.json", type: "glossary" as const },
  { file: "review_config.json", type: "config" as const },
];

function scanDirectory(dir: string) {
  const results: { type: "report" | "glossary" | "config"; path: string; name: string }[] = [];
  for (const target of SCAN_TARGETS) {
    const fp = path.join(dir, target.file);
    if (fs.existsSync(fp)) {
      results.push({ type: target.type, path: fp, name: target.file });
    }
  }
  return results;
}

function findInParentDirs(startDir: string) {
  let current = path.resolve(startDir);
  const root = path.parse(current).root;
  while (true) {
    const r = scanDirectory(current);
    if (r.length > 0) return r;
    if (current === root) break;
    current = path.dirname(current);
  }
  return [];
}

function scanAll() {
  const appPath = app.getAppPath();
  const cwd = process.cwd();
  const results: { type: "report" | "glossary" | "config"; path: string; name: string }[] = [];

  // 1. Scan output/ subdirectory
  const outputDir = path.join(cwd, "output");
  if (fs.existsSync(outputDir)) {
    results.push(...scanDirectory(outputDir));
  }

  // 2. Scan cwd
  results.push(...scanDirectory(cwd));
  results.push(...scanDirectory(appPath));

  // 3. Walk up from cwd
  if (results.length === 0) {
    results.push(...findInParentDirs(cwd));
  }

  // Deduplicate by type
  const seen = new Set<string>();
  const deduped: typeof results = [];
  for (const r of results) {
    if (!seen.has(r.type)) {
      seen.add(r.type);
      deduped.push(r);
    }
  }
  return { found: deduped };
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: "审校工具 - Minecraft Mod Translate",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }
}

function setupIPC() {
  ipcMain.handle("scan-files", () => {
    return scanAll();
  });

  ipcMain.handle("read-file", async (_event, filePath: string) => {
    const content = fs.readFileSync(filePath, "utf-8");
    return JSON.parse(content);
  });

  ipcMain.handle("get-app-path", () => {
    return process.cwd();
  });
}

app.whenReady().then(() => {
  setupIPC();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
