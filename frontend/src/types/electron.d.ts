interface ScannedFile {
  type: "report" | "glossary" | "config";
  path: string;
  name: string;
}

interface ElectronAPI {
  scanFiles(): Promise<{ found: ScannedFile[] }>;
  readFile<T>(filePath: string): Promise<T>;
  getAppPath(): Promise<string>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
