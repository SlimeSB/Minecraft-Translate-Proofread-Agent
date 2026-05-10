import { useState } from "react";
import { useReportStore } from "../stores/useReportStore";
import { VERDICT_COLORS, type VerdictDict } from "../types/report";
import StatCard from "../components/StatCard";

const SOURCE_LABELS: Record<string, string> = {
  format_check: "格式检查",
  terminology_check: "术语检查",
  llm_review: "LLM 审校",
  interactive: "交互判定",
  pr_warning: "PR 警告",
  llm_error: "LLM 错误",
};

export default function ReviewPage() {
  const store = useReportStore();
  const { report, filters, filteredVerdicts, namespaces, sources } = store;
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  if (!report) {
    return (
      <div className="p-12 text-center text-gray-400">
        <p className="text-4xl mb-4">📋</p>
        <p>请先在首页加载 report.json</p>
      </div>
    );
  }

  const filtered = filteredVerdicts();
  const allNamespaces = namespaces();
  const allSources = sources();

  const stats = [
    { label: "总计", value: report.stats.total, color: "bg-gray-500" },
    { label: "FAIL", value: report.stats.FAIL, color: "bg-red-500" },
    { label: "REVIEW", value: report.stats.REVIEW, color: "bg-orange-500" },
    { label: "SUGGEST", value: report.stats.SUGGEST, color: "bg-yellow-500" },
    { label: "PASS", value: report.stats.PASS, color: "bg-green-500" },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {stats.map((s) => (
          <StatCard key={s.label} {...s} />
        ))}
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3 shadow-sm">
        {/* Verdict tags */}
        <div className="flex flex-wrap gap-2">
          {["❌ FAIL", "🔶 REVIEW", "⚠️ SUGGEST", "PASS"].map((v) => {
            const active = filters.verdictFilter.has(v);
            return (
              <button
                key={v}
                onClick={() => filters.toggleVerdict(v)}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  active
                    ? VERDICT_COLORS[v]
                    : "border-gray-200 text-gray-400 hover:border-gray-300"
                }`}
              >
                {v}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap gap-3">
          {/* Source filter */}
          <select
            value={Array.from(filters.sourceFilter).join(",")}
            onChange={(e) =>
              filters.setSourceFilter(
                e.target.value ? new Set(e.target.value.split(",")) : new Set()
              )
            }
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
          >
            <option value="">全部来源</option>
            {allSources.map((s) => (
              <option key={s} value={s}>
                {SOURCE_LABELS[s] || s}
              </option>
            ))}
          </select>

          {/* Namespace filter */}
          <select
            value={filters.namespaceFilter}
            onChange={(e) => filters.setNamespaceFilter(e.target.value)}
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
          >
            <option value="">全部命名空间</option>
            {allNamespaces.map((ns) => (
              <option key={ns} value={ns}>
                {ns}
              </option>
            ))}
          </select>

          {/* Keyword search */}
          <input
            type="text"
            placeholder="搜索 key / EN / ZH..."
            value={filters.keywordFilter}
            onChange={(e) => filters.setKeywordFilter(e.target.value)}
            className="flex-1 min-w-[200px] px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />

          {(filters.verdictFilter.size > 0 ||
            filters.sourceFilter.size > 0 ||
            filters.namespaceFilter ||
            filters.keywordFilter) && (
            <button
              onClick={filters.resetFilters}
              className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700"
            >
              清除筛选
            </button>
          )}
        </div>

        <p className="text-xs text-gray-400">
          共 {report.verdicts.length} 条，筛选后 {filtered.length} 条
        </p>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 w-24">等级</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 w-28">来源</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">Key</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 w-80">EN</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 w-80">ZH</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((v) => (
              <VerdictRow
                key={v.key}
                verdict={v}
                expanded={expandedKey === v.key}
                onToggle={() =>
                  setExpandedKey(expandedKey === v.key ? null : v.key)
                }
              />
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="text-center py-12 text-gray-400">
                  没有匹配的审校意见
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function VerdictRow({
  verdict: v,
  expanded,
  onToggle,
}: {
  verdict: VerdictDict;
  expanded: boolean;
  onToggle: () => void;
}) {
  const colorClass = VERDICT_COLORS[v.verdict] || "bg-gray-100 text-gray-800";
  return (
    <>
      <tr
        className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
        onClick={onToggle}
      >
        <td className="px-4 py-3">
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${colorClass}`}>
            {v.verdict}
          </span>
        </td>
        <td className="px-4 py-3 text-xs text-gray-500">{v.source}</td>
        <td className="px-4 py-3 font-mono text-xs text-gray-700 max-w-[200px] truncate" title={v.key}>
          {v.key}
        </td>
        <td className="px-4 py-3 text-xs text-gray-600 max-w-[300px] truncate" title={v.en_current}>
          {v.en_current}
        </td>
        <td className="px-4 py-3 text-xs text-gray-600 max-w-[300px] truncate" title={v.zh_current}>
          {v.zh_current}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50 border-b border-gray-100">
          <td colSpan={5} className="px-6 py-4">
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-xs text-gray-400 mb-1">EN (完整)</p>
                <p className="text-gray-700 bg-white rounded-lg p-3 border border-gray-200 whitespace-pre-wrap break-words">
                  {v.en_current}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-400 mb-1">ZH (完整)</p>
                <p className="text-gray-700 bg-white rounded-lg p-3 border border-gray-200 whitespace-pre-wrap break-words">
                  {v.zh_current}
                </p>
              </div>
              {v.suggestion && (
                <div>
                  <p className="text-xs text-gray-400 mb-1">建议修改</p>
                  <p className="text-blue-700 bg-blue-50 rounded-lg p-3 border border-blue-200 whitespace-pre-wrap break-words">
                    {v.suggestion}
                  </p>
                </div>
              )}
              <div>
                <p className="text-xs text-gray-400 mb-1">原因</p>
                <p className="text-gray-600 bg-white rounded-lg p-3 border border-gray-200 whitespace-pre-wrap break-words">
                  {v.reason}
                </p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
