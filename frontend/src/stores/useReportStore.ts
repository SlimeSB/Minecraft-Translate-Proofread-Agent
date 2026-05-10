import { create } from "zustand";
import type { ReviewReport, VerdictDict } from "../types/report";

interface FilterState {
  verdictFilter: Set<string>;
  sourceFilter: Set<string>;
  namespaceFilter: string;
  keywordFilter: string;
  setVerdictFilter: (v: Set<string>) => void;
  toggleVerdict: (v: string) => void;
  setSourceFilter: (s: Set<string>) => void;
  toggleSource: (s: string) => void;
  setNamespaceFilter: (ns: string) => void;
  setKeywordFilter: (kw: string) => void;
  resetFilters: () => void;
}

interface ReportState {
  report: ReviewReport | null;
  loaded: boolean;
  loadReport: (r: ReviewReport) => void;
  clearReport: () => void;
  filteredVerdicts: () => VerdictDict[];
  namespaces: () => string[];
  sources: () => string[];
  filters: FilterState;
}

const initialFilters = {
  verdictFilter: new Set<string>(),
  sourceFilter: new Set<string>(),
  namespaceFilter: "",
  keywordFilter: "",
};

export const useReportStore = create<ReportState>((set, get) => ({
  report: null,
  loaded: false,
  loadReport: (r) => set({ report: r, loaded: true }),
  clearReport: () => set({ report: null, loaded: false }),
  filters: {
    ...initialFilters,
    setVerdictFilter: (v) =>
      set((s) => ({ filters: { ...s.filters, verdictFilter: v } })),
    toggleVerdict: (v) =>
      set((s) => {
        const next = new Set(s.filters.verdictFilter);
        next.has(v) ? next.delete(v) : next.add(v);
        return { filters: { ...s.filters, verdictFilter: next } };
      }),
    setSourceFilter: (s) =>
      set((st) => ({ filters: { ...st.filters, sourceFilter: s } })),
    toggleSource: (src) =>
      set((s) => {
        const next = new Set(s.filters.sourceFilter);
        next.has(src) ? next.delete(src) : next.add(src);
        return { filters: { ...s.filters, sourceFilter: next } };
      }),
    setNamespaceFilter: (ns) =>
      set((s) => ({ filters: { ...s.filters, namespaceFilter: ns } })),
    setKeywordFilter: (kw) =>
      set((s) => ({ filters: { ...s.filters, keywordFilter: kw } })),
    resetFilters: () => set({ filters: { ...initialFilters, ...get().filters } }),
  },
  filteredVerdicts: () => {
    const { report, filters } = get();
    if (!report) return [];
    let list = report.verdicts;
    if (filters.verdictFilter.size > 0) {
      list = list.filter((v) => filters.verdictFilter.has(v.verdict));
    }
    if (filters.sourceFilter.size > 0) {
      list = list.filter((v) => filters.sourceFilter.has(v.source));
    }
    if (filters.namespaceFilter) {
      const ns = filters.namespaceFilter;
      list = list.filter((v) => v.key.startsWith(ns));
    }
    if (filters.keywordFilter) {
      const kw = filters.keywordFilter.toLowerCase();
      list = list.filter(
        (v) =>
          v.key.toLowerCase().includes(kw) ||
          v.en_current.toLowerCase().includes(kw) ||
          v.zh_current.toLowerCase().includes(kw)
      );
    }
    return list;
  },
  namespaces: () => {
    const { report } = get();
    if (!report) return [];
    const nsSet = new Set<string>();
    for (const v of report.verdicts) {
      const ns = v.key.includes(":") ? v.key.split(":")[0] : "default";
      nsSet.add(ns);
    }
    return Array.from(nsSet).sort();
  },
  sources: () => {
    const { report } = get();
    if (!report) return [];
    return Array.from(new Set(report.verdicts.map((v) => v.source))).sort();
  },
}));
