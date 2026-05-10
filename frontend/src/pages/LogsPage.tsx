import { usePipelineStore, type LogEntry } from "../stores/usePipelineStore";

const LEVEL_COLORS: Record<string, string> = {
  INFO: "text-blue-600",
  WARN: "text-yellow-600",
  ERROR: "text-red-600",
};

const LEVEL_BG: Record<string, string> = {
  INFO: "bg-blue-50",
  WARN: "bg-yellow-50",
  ERROR: "bg-red-50",
};

const MOCK_LOGS: LogEntry[] = [
  { level: "INFO", message: "Phase 1 — 键对齐完成 (matched: 1243, missing: 12)", timestamp: "00:00:01" },
  { level: "INFO", message: "Phase 2 — 术语提取: 156 条术语", timestamp: "00:00:03" },
  { level: "WARN", message: "术语 'upgrade' 出现 2 次，低于最低频率阈值", timestamp: "00:00:03" },
  { level: "INFO", message: "Phase 3a — 格式检查: 23 条问题", timestamp: "00:00:04" },
  { level: "INFO", message: "Phase 3b — 模糊搜索完成", timestamp: "00:00:05" },
  { level: "INFO", message: "Phase 3c — LLM 审校开始 (batch_size=25)", timestamp: "00:00:06" },
  { level: "INFO", message: "Token 用量: prompt=12450, completion=3200, total=15650", timestamp: "00:00:12" },
  { level: "ERROR", message: "API 请求失败 (429 Too Many Requests), 重试中...", timestamp: "00:00:13" },
  { level: "INFO", message: "重试成功 (第 2 次)", timestamp: "00:00:16" },
  { level: "INFO", message: "Phase 4 — LLM 过滤: 驳回 5 条, 保留 18 条", timestamp: "00:00:20" },
  { level: "INFO", message: "Phase 5 — 报告生成完成", timestamp: "00:00:21" },
];

export default function LogsPage() {
  const pipelineLogs = usePipelineStore((s) => s.logs);
  const status = usePipelineStore((s) => s.status);
  const logs = pipelineLogs.length > 0 ? pipelineLogs : MOCK_LOGS;

  const tokenInfo = {
    prompt: 12450,
    completion: 3200,
    total: 15650,
    phases: [
      { name: "Phase 1 对齐", time: "1.2s" },
      { name: "Phase 2 术语", time: "2.8s" },
      { name: "Phase 3a 格式", time: "0.5s" },
      { name: "Phase 3b 模糊", time: "0.8s" },
      { name: "Phase 3c LLM", time: "14.2s" },
      { name: "Phase 4 过滤", time: "5.1s" },
      { name: "Phase 5 报告", time: "0.3s" },
    ],
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <h2 className="text-xl font-bold text-gray-800">运行日志</h2>

      {/* Status */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">状态:</span>
          <span
            className={`px-3 py-1 rounded-full text-xs font-medium ${
              status === "idle"
                ? "bg-gray-100 text-gray-500"
                : status === "running"
                  ? "bg-blue-100 text-blue-700"
                  : status === "done"
                    ? "bg-green-100 text-green-700"
                    : "bg-red-100 text-red-700"
            }`}
          >
            {status === "idle" ? "等待运行" : status === "running" ? "运行中..." : status === "done" ? "已完成" : "错误"}
          </span>
        </div>
      </div>

      {/* Token Usage */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Token 用量</h3>
        <div className="space-y-2">
          <TokenBar label="Prompt" value={tokenInfo.prompt} total={tokenInfo.total} color="bg-blue-500" />
          <TokenBar label="Completion" value={tokenInfo.completion} total={tokenInfo.total} color="bg-green-500" />
          <div className="pt-2 text-right text-xs text-gray-400">
            总计: <strong>{tokenInfo.total.toLocaleString()}</strong> tokens
          </div>
        </div>
      </div>

      {/* Phase Times */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">阶段耗时</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {tokenInfo.phases.map((p) => (
            <div key={p.name} className="bg-gray-50 rounded-lg p-3 text-center">
              <p className="text-xs text-gray-400">{p.name}</p>
              <p className="text-lg font-bold text-gray-700">{p.time}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Log Stream */}
      <div className="bg-gray-900 rounded-xl border border-gray-700 shadow-sm overflow-hidden">
        <div className="px-4 py-2 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-400" />
          <span className="text-xs text-gray-300">日志输出</span>
        </div>
        <div className="p-3 space-y-0.5 max-h-[400px] overflow-y-auto font-mono text-xs">
          {logs.map((log, i) => (
            <div key={i} className={`${LEVEL_BG[log.level]} rounded px-2 py-0.5`}>
              <span className="text-gray-500">[{log.timestamp}]</span>{" "}
              <span className={`font-medium ${LEVEL_COLORS[log.level]}`}>
                [{log.level}]
              </span>{" "}
              <span className="text-gray-700">{log.message}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TokenBar({
  label,
  value,
  total,
  color,
}: {
  label: string;
  value: number;
  total: number;
  color: string;
}) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{label}</span>
        <span>{value.toLocaleString()}</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className={`h-2 rounded-full ${color} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
