import { useEffect, useState } from "react";
import { useReportStore } from "../stores/useReportStore";
import { useGlossaryStore } from "../stores/useGlossaryStore";
import type { ReviewReport } from "../types/report";
import type { GlossaryEntry } from "../types/glossary";

export interface ScanFileInfo {
  type: "report" | "glossary" | "config";
  path: string;
  name: string;
  loaded: boolean;
  error?: string;
}

export interface ScanState {
  scanning: boolean;
  files: ScanFileInfo[];
  mode: "electron" | "server" | "none";
}

const SCAN_SERVER_URL = "http://localhost:8000";

async function tryServerScan(): Promise<{
  files: ScanFileInfo[];
  serverUrl: string;
}> {
  const serverUrl =
    localStorage.getItem("scan_server_url") || SCAN_SERVER_URL;
  const res = await fetch(`${serverUrl}/api/scan-files`, {
    signal: AbortSignal.timeout(3000),
  });
  if (!res.ok) throw new Error(`Server returned ${res.status}`);
  const result: { found: Omit<ScanFileInfo, "loaded">[] } = await res.json();
  return {
    files: result.found.map((f) => ({ ...f, loaded: false })),
    serverUrl,
  };
}

async function tryServerRead<T>(path: string, serverUrl: string): Promise<T> {
  const res = await fetch(
    `${serverUrl}/api/read-file?path=${encodeURIComponent(path)}`,
    { signal: AbortSignal.timeout(10000) }
  );
  if (!res.ok) throw new Error(`Server read returned ${res.status}`);
  return res.json();
}

async function loadFileData(
  file: ScanFileInfo,
  loadReport: (r: ReviewReport) => void,
  loadGlossary: (e: GlossaryEntry[]) => void,
  loadStopWords: (w: string[]) => void,
  mode: "electron" | "server",
  serverUrl?: string
): Promise<ScanFileInfo> {
  try {
    let data: unknown;
    if (mode === "electron") {
      data = await window.electronAPI!.readFile(file.path);
    } else if (mode === "server" && serverUrl) {
      data = await tryServerRead(file.path, serverUrl);
    } else {
      return { ...file, error: "No reader available" };
    }

    switch (file.type) {
      case "report":
        loadReport(data as ReviewReport);
        break;
      case "glossary":
        if (Array.isArray(data)) {
          loadGlossary(data as GlossaryEntry[]);
        } else if (
          data &&
          typeof data === "object" &&
          "glossary" in (data as Record<string, unknown>)
        ) {
          loadGlossary((data as { glossary: GlossaryEntry[] }).glossary);
        }
        break;
      case "config": {
        const cfg = data as { terminology?: { blacklist?: string[] } };
        if (cfg?.terminology?.blacklist) {
          loadStopWords(cfg.terminology.blacklist);
        }
        break;
      }
    }
    return { ...file, loaded: true };
  } catch (err) {
    return { ...file, error: String(err) };
  }
}

export function useAutoScan() {
  const loadReport = useReportStore((s) => s.loadReport);
  const loadGlossary = useGlossaryStore((s) => s.loadGlossary);
  const loadStopWords = useGlossaryStore((s) => s.loadStopWordsFromConfig);
  const [state, setState] = useState<ScanState>({
    scanning: true,
    files: [],
    mode: "none",
  });

  useEffect(() => {
    const hasElectron =
      typeof window !== "undefined" && !!window.electronAPI;

    (async () => {
      // Try Electron first
      if (hasElectron) {
        try {
          const result = await window.electronAPI!.scanFiles();
          if (result.found.length > 0) {
            const files: ScanFileInfo[] = result.found.map((f) => ({
              ...f,
              loaded: false,
            }));
            setState({ scanning: false, files, mode: "electron" });
            for (const file of files) {
              const updated = await loadFileData(
                file,
                loadReport,
                loadGlossary,
                loadStopWords,
                "electron"
              );
              setState((s) => ({
                ...s,
                files: s.files.map((f) =>
                  f.path === file.path ? updated : f
                ),
              }));
            }
            return;
          }
        } catch {
          // Electron scan failed, fall through to server scan
        }
      }

      // Try server scan
      try {
        const { files, serverUrl } = await tryServerScan();
        if (files.length > 0) {
          setState({ scanning: false, files, mode: "server" });
          for (const file of files) {
            const updated = await loadFileData(
              file,
              loadReport,
              loadGlossary,
              loadStopWords,
              "server",
              serverUrl
            );
            setState((s) => ({
              ...s,
              files: s.files.map((f) =>
                f.path === file.path ? updated : f
              ),
            }));
          }
          return;
        }
      } catch {
        // Server not available, manual upload only
      }

      setState({ scanning: false, files: [], mode: "none" });
    })();
  }, [loadReport, loadGlossary, loadStopWords]);

  return state;
}
