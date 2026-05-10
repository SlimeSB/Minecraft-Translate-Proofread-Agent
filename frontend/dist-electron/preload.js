"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
electron_1.contextBridge.exposeInMainWorld("electronAPI", {
    scanFiles: () => electron_1.ipcRenderer.invoke("scan-files"),
    readFile: (filePath) => electron_1.ipcRenderer.invoke("read-file", filePath),
    getAppPath: () => electron_1.ipcRenderer.invoke("get-app-path"),
});
