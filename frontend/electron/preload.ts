import { contextBridge, ipcRenderer } from "electron";

export interface ScannedFile {
  type: "report" | "glossary" | "config";
  path: string;
  name: string;
}

export interface ElectronAPI {
  scanFiles(): Promise<{ found: ScannedFile[] }>;
  readFile<T>(filePath: string): Promise<T>;
  getAppPath(): Promise<string>;
}

contextBridge.exposeInMainWorld("electronAPI", {
  scanFiles: () => ipcRenderer.invoke("scan-files"),
  readFile: <T>(filePath: string) => ipcRenderer.invoke("read-file", filePath),
  getAppPath: () => ipcRenderer.invoke("get-app-path"),
});
