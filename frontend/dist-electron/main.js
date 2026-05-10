"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const path = __importStar(require("path"));
const fs = __importStar(require("fs"));
let mainWindow = null;
const SCAN_TARGETS = [
    { file: "report.json", type: "report" },
    { file: "glossary.json", type: "glossary" },
    { file: "review_config.json", type: "config" },
];
function scanDirectory(dir) {
    const results = [];
    for (const target of SCAN_TARGETS) {
        const fp = path.join(dir, target.file);
        if (fs.existsSync(fp)) {
            results.push({ type: target.type, path: fp, name: target.file });
        }
    }
    return results;
}
function findInParentDirs(startDir) {
    let current = path.resolve(startDir);
    const root = path.parse(current).root;
    while (true) {
        const r = scanDirectory(current);
        if (r.length > 0)
            return r;
        if (current === root)
            break;
        current = path.dirname(current);
    }
    return [];
}
function scanAll() {
    const appPath = electron_1.app.getAppPath();
    const cwd = process.cwd();
    const results = [];
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
    const seen = new Set();
    const deduped = [];
    for (const r of results) {
        if (!seen.has(r.type)) {
            seen.add(r.type);
            deduped.push(r);
        }
    }
    return { found: deduped };
}
function createWindow() {
    mainWindow = new electron_1.BrowserWindow({
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
    }
    else {
        mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
    }
}
function setupIPC() {
    electron_1.ipcMain.handle("scan-files", () => {
        return scanAll();
    });
    electron_1.ipcMain.handle("read-file", async (_event, filePath) => {
        const content = fs.readFileSync(filePath, "utf-8");
        return JSON.parse(content);
    });
    electron_1.ipcMain.handle("get-app-path", () => {
        return process.cwd();
    });
}
electron_1.app.whenReady().then(() => {
    setupIPC();
    createWindow();
    electron_1.app.on("activate", () => {
        if (electron_1.BrowserWindow.getAllWindows().length === 0)
            createWindow();
    });
});
electron_1.app.on("window-all-closed", () => {
    if (process.platform !== "darwin")
        electron_1.app.quit();
});
