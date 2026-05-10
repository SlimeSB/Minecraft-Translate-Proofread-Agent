import { useState } from "react";

const DUMMY_RESULTS = [
  { engine: "Dummy Engine", text: "[模拟翻译结果] 这是一个占位翻译结果" },
];

export default function TranslatePage() {
  const [input, setInput] = useState("");
  const [results, setResults] = useState<typeof DUMMY_RESULTS>([]);

  const handleTranslate = () => {
    if (!input.trim()) return;
    setResults(DUMMY_RESULTS);
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <h2 className="text-xl font-bold text-gray-800">翻译（开发中）</h2>
      <p className="text-sm text-gray-400">
        此功能正在开发中。以下是翻译引擎接口预留和占位页面。
      </p>

      {/* Engine List */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">已注册引擎</h3>
        <div className="space-y-2">
          <EngineCard name="Dummy Engine" description="哑引擎，返回模拟翻译结果" status="active" />
          <EngineCard name="OpenAI Engine" description="通过 API 配置读取 Base URL 和 Key" status="ready" />
          <EngineCard name="TranslateEngine 接口" description="TranslateEngine { name, translate(), supports() }" status="interface" />
        </div>
      </div>

      {/* Demo Translate UI */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">翻译演示</h3>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入要翻译的英文文本..."
          rows={4}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
        />
        <button
          onClick={handleTranslate}
          disabled={!input.trim()}
          className="mt-3 px-6 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
        >
          翻译
        </button>
        {results.length > 0 && (
          <div className="mt-4 space-y-2">
            {results.map((r, i) => (
              <div key={i} className="bg-blue-50 rounded-lg p-3 border border-blue-200">
                <p className="text-xs text-blue-500 mb-1">{r.engine}</p>
                <p className="text-sm text-gray-700">{r.text}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EngineCard({
  name,
  description,
  status,
}: {
  name: string;
  description: string;
  status: string;
}) {
  const statusColor =
    status === "active"
      ? "bg-green-100 text-green-700"
      : status === "ready"
        ? "bg-blue-100 text-blue-700"
        : "bg-gray-100 text-gray-500";

  return (
    <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
      <div>
        <p className="text-sm font-medium text-gray-700">{name}</p>
        <p className="text-xs text-gray-400">{description}</p>
      </div>
      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusColor}`}>
        {status}
      </span>
    </div>
  );
}
