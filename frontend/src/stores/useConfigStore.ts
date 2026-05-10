import { create } from "zustand";
import type { APIConfig } from "../types/config";

interface ConfigState {
  sites: APIConfig[];
  activeId: string | null;
  addSite: (site: Omit<APIConfig, "id" | "active">) => void;
  updateSite: (id: string, data: Partial<APIConfig>) => void;
  removeSite: (id: string) => void;
  setActive: (id: string) => void;
  getActive: () => APIConfig | undefined;
  _hydrated: boolean;
  hydrate: () => void;
}

function save(sites: APIConfig[], activeId: string | null) {
  try {
    localStorage.setItem("api_sites", JSON.stringify(sites));
    localStorage.setItem("api_active", activeId ?? "");
  } catch {}
}

export const useConfigStore = create<ConfigState>((set, get) => ({
  sites: [],
  activeId: null,
  _hydrated: false,
  hydrate: () => {
    try {
      const raw = localStorage.getItem("api_sites");
      const sites: APIConfig[] = raw ? JSON.parse(raw) : [];
      const activeId = localStorage.getItem("api_active") || null;
      set({ sites, activeId, _hydrated: true });
    } catch {
      set({ _hydrated: true });
    }
  },
  addSite: (data) =>
    set((s) => {
      const id = crypto.randomUUID();
      const site: APIConfig = { ...data, id, active: s.sites.length === 0 };
      const sites = [...s.sites, site];
      const activeId = site.active ? id : s.activeId;
      save(sites, activeId);
      return { sites, activeId };
    }),
  updateSite: (id, data) =>
    set((s) => {
      const sites = s.sites.map((site) =>
        site.id === id ? { ...site, ...data } : site
      );
      save(sites, s.activeId);
      return { sites };
    }),
  removeSite: (id) =>
    set((s) => {
      const sites = s.sites.filter((site) => site.id !== id);
      const activeId = s.activeId === id ? sites[0]?.id ?? null : s.activeId;
      save(sites, activeId);
      return { sites, activeId };
    }),
  setActive: (id) =>
    set((s) => {
      const sites = s.sites.map((site) => ({
        ...site,
        active: site.id === id,
      }));
      save(sites, id);
      return { sites, activeId: id };
    }),
  getActive: () => {
    const { sites, activeId } = get();
    return sites.find((s) => s.id === activeId);
  },
}));
