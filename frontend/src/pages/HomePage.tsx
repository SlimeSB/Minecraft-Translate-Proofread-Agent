import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import FileDropzone from "../components/FileDropzone";
import { useReportStore } from "../stores/useReportStore";
import { useGlossaryStore } from "../stores/useGlossaryStore";
import { useConfigStore } from "../stores/useConfigStore";
import { usePipelineStore } from "../stores/usePipelineStore";
import { useAutoScan, type ScanFileInfo } from "../hooks/useAutoScan";
import type { ReviewReport } from "../types/report";
import type { GlossaryEntry } from "../types/glossary";

const FILE_LABELS: Record<string, string> = {
  report: "📋 report.json",
  glossary: "📖 glossary.json",
  config: "⚙️ review_config.json",
};

export default function HomePage() {
  const navigate = useNavigate();
  const loadReport = useReportStore((s) => s.loadReport);
  const reportLoaded = useReportStore((s) => s.loaded);
  const loadGlossary = useGlossaryStore((s) => s.loadGlossary);
  const loadStopWords = useGlossaryStore((s) => s.loadStopWordsFromConfig);
  const sites = useConfigStore((s) => s.sites);
  const addSite = useConfigStore((s) => s.addSite);
  const removeSite = useConfigStore((s) => s.removeSite);
  const setActive = useConfigStore((s) => s.setActive);
  const hydrate = useConfigStore((s) => s.hydrate);
  const prNumber = usePipelineStore((s) => s.prNumber);
  const setPrNumber = usePipelineStore((s) => s.setPrNumber);
  const scan = useAutoScan();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  const handleReportLoad = (data: unknown) => {
    loadReport(data as ReviewReport);
  };

  const handleGlossaryLoad = (data: unknown) => {
    if (Array.isArray(data)) {
      loadGlossary(data as GlossaryEntry[]);
    } else if (data && typeof data === "object" && "glossary" in (data as Record<string, unknown>)) {
      loadGlossary((data as { glossary: GlossaryEntry[] }).glossary);
    } else {
      alert("术语表格式不正确，需要是数组或 { glossary: [...] } 结构");
    }
  };

  const handleConfigLoad = (data: unknown) => {
    const cfg = data as { terminology?: { blacklist?: string[] } };
    if (cfg?.terminology?.blacklist) {
      loadStopWords(cfg.terminology.blacklist);
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-gray-800">欢迎使用审校工具</h2>
        <p className="text-gray-500 mt-1">
          {scan.mode === "electron"
            ? "桌面模式 — 自动扫描本地文件，或拖拽 JSON 手动加载"
            : scan.mode === "server"
              ? "服务器模式 — 自动检测远端产出，或拖拽 JSON 手动加载"
              : "拖拽审校报告、术语表和配置文件开始使用"}
        </p>
      </div>

      {/* Auto-scan results */}
      {scan.mode !== "none" && (
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">
            {scan.scanning ? "正在扫描..." : "自动扫描结果"}
          </h3>
          {scan.scanning ? (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
              扫描中...
            </div>
          ) : scan.files.length === 0 ? (
            <p className="text-sm text-gray-400">
              未自动发现产出文件。请手动拖拽上传，或运行
              <code className="mx-1 px-1 py-0.5 bg-gray-100 rounded text-xs">python run.py</code>
              生成。
            </p>
          ) : (
            <div className="space-y-2">
              {scan.files.map((file) => (
                <ScanFileRow key={file.path} file={file} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Manual File Dropzones — always available */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3">
          {scan.mode !== "none" ? "手动上传（备用）" : "上传文件"}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <FileDropzone
            onLoad={handleReportLoad}
            acceptLabel="report.json"
            icon="📋"
          />
          <FileDropzone
            onLoad={handleGlossaryLoad}
            acceptLabel="glossary.json"
            icon="📖"
          />
          <FileDropzone
            onLoad={handleConfigLoad}
            acceptLabel="review_config.json"
            icon="⚙️"
          />
        </div>
      </div>

      {/* PR Input */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">PR 快速加载</h3>
        <div className="flex gap-3">
          <input
            type="text"
            placeholder="输入 PR 编号 (如 5979)"
            value={prNumber}
            onChange={(e) => setPrNumber(e.target.value)}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <button className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
            disabled={!prNumber}>
            加载
          </button>
        </div>
      </div>

      {/* API Config */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">API 配置</h3>
        <div className="space-y-2 mb-4">
          {sites.map((site) => (
            <div
              key={site.id}
              className={`flex items-center justify-between p-3 rounded-lg border text-sm ${
                site.active
                  ? "border-blue-300 bg-blue-50"
                  : "border-gray-200"
              }`}
            >
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setActive(site.id)}
                  className={`w-4 h-4 rounded-full border-2 ${
                    site.active
                      ? "border-blue-500 bg-blue-500"
                      : "border-gray-300"
                  }`}
                />
                <div>
                  <p className="font-medium">{site.name}</p>
                  <p className="text-xs text-gray-400">{site.baseUrl}</p>
                </div>
              </div>
              <button
                onClick={() => removeSite(site.id)}
                className="text-red-400 hover:text-red-600 text-xs"
              >
                删除
              </button>
            </div>
          ))}
        </div>
        <AddSiteForm onAdd={addSite} />
      </div>

      {/* Start Button */}
      {reportLoaded && (
        <div className="flex justify-center">
          <button
            onClick={() => navigate("/review")}
            className="px-8 py-3 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors shadow-lg"
          >
            开始审校 →
          </button>
        </div>
      )}
    </div>
  );
}

function ScanFileRow({ file }: { file: ScanFileInfo }) {
  const statusIcon = file.error ? "❌" : file.loaded ? "✅" : "⏳";
  const statusText = file.error
    ? "加载失败"
    : file.loaded
      ? "已加载"
      : "等待加载";
  return (
    <div className="flex items-center justify-between p-2.5 bg-gray-50 rounded-lg text-sm">
      <div className="flex items-center gap-2">
        <span>{statusIcon}</span>
        <span className="font-mono text-xs text-gray-700">
          {FILE_LABELS[file.type] || file.name}
        </span>
        <span className="text-xs text-gray-400 truncate max-w-[200px]">
          {file.path}
        </span>
      </div>
      <span className="text-xs text-gray-500">{statusText}</span>
    </div>
  );
}

function AddSiteForm({ onAdd }: { onAdd: (site: { name: string; baseUrl: string; apiKey: string }) => void }) {
  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const name = fd.get("name") as string;
    const baseUrl = fd.get("baseUrl") as string;
    const apiKey = fd.get("apiKey") as string;
    if (!name || !baseUrl || !apiKey) return;
    onAdd({ name, baseUrl, apiKey });
    (e.target as HTMLFormElement).reset();
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap gap-2">
      <input
        name="name"
        placeholder="名称 (如 DeepSeek)"
        className="flex-1 min-w-[120px] px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
      />
      <input
        name="baseUrl"
        placeholder="Base URL"
        className="flex-1 min-w-[180px] px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
      />
      <input
        name="apiKey"
        type="password"
        placeholder="API Key"
        className="flex-1 min-w-[140px] px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
      />
      <button
        type="submit"
        className="px-4 py-2 bg-gray-700 text-white text-sm rounded-lg hover:bg-gray-800 transition-colors"
      >
        添加
      </button>
    </form>
  );
}
