import { create } from "zustand";

interface PipelineState {
  prNumber: string;
  status: "idle" | "running" | "done" | "error";
  logs: LogEntry[];
  setPrNumber: (n: string) => void;
  setStatus: (s: PipelineState["status"]) => void;
  addLog: (log: LogEntry) => void;
  clearLogs: () => void;
}

export interface LogEntry {
  level: "INFO" | "WARN" | "ERROR";
  message: string;
  timestamp: string;
}

export const usePipelineStore = create<PipelineState>((set) => ({
  prNumber: "",
  status: "idle",
  logs: [],
  setPrNumber: (n) => set({ prNumber: n }),
  setStatus: (s) => set({ status: s }),
  addLog: (log) => set((s) => ({ logs: [...s.logs, log] })),
  clearLogs: () => set({ logs: [] }),
}));
