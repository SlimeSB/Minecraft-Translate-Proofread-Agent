import { create } from "zustand";
import type { GlossaryEntry } from "../types/glossary";

interface GlossaryState {
  entries: GlossaryEntry[];
  loaded: boolean;
  stopWords: string[];
  loadGlossary: (entries: GlossaryEntry[]) => void;
  clearGlossary: () => void;
  toggleStopWord: (en: string) => void;
  addStopWord: (word: string) => void;
  removeStopWord: (word: string) => void;
  loadStopWordsFromConfig: (blacklist: string[]) => void;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  filteredEntries: () => GlossaryEntry[];
}

export const useGlossaryStore = create<GlossaryState>((set, get) => ({
  entries: [],
  loaded: false,
  stopWords: [],
  loadGlossary: (entries) => set({ entries, loaded: true }),
  clearGlossary: () => set({ entries: [], loaded: false }),
  toggleStopWord: (en) =>
    set((s) => ({
      stopWords: s.stopWords.includes(en)
        ? s.stopWords.filter((w) => w !== en)
        : [...s.stopWords, en],
    })),
  addStopWord: (word) =>
    set((s) => ({
      stopWords: s.stopWords.includes(word) ? s.stopWords : [...s.stopWords, word],
    })),
  removeStopWord: (word) =>
    set((s) => ({
      stopWords: s.stopWords.filter((w) => w !== word),
    })),
  loadStopWordsFromConfig: (blacklist) => set({ stopWords: blacklist }),
  searchQuery: "",
  setSearchQuery: (q) => set({ searchQuery: q }),
  filteredEntries: () => {
    const { entries, searchQuery } = get();
    if (!searchQuery) return entries;
    const q = searchQuery.toLowerCase();
    return entries.filter(
      (e) => e.en.toLowerCase().includes(q) || e.zh.toLowerCase().includes(q)
    );
  },
}));
