import { useState } from "react";
import { useGlossaryStore } from "../stores/useGlossaryStore";

export default function GlossaryPage() {
  const store = useGlossaryStore();
  const { stopWords, searchQuery, setSearchQuery, filteredEntries, toggleStopWord, addStopWord, removeStopWord } = store;
  const [newStopWord, setNewStopWord] = useState("");
  const filtered = filteredEntries();

  if (!store.loaded) {
    return (
      <div className="p-12 text-center text-gray-400">
        <p className="text-4xl mb-4">📖</p>
        <p>请先在首页加载 glossary.json</p>
      </div>
    );
  }

  const handleExport = () => {
    const blob = new Blob(
      [
        JSON.stringify(
          { terminology: { blacklist: stopWords } },
          null,
          2
        ),
      ],
      { type: "application/json" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "review_config.blacklist.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-800">术语表</h2>
          <p className="text-sm text-gray-500">
            共 {store.entries.length} 条术语，{stopWords.length} 条停用词
          </p>
        </div>
        <button
          onClick={handleExport}
          className="px-4 py-2 bg-gray-700 text-white text-sm rounded-lg hover:bg-gray-800 transition-colors"
        >
          导出停用词 ↓
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Table */}
        <div className="lg:col-span-3 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="p-3 border-b border-gray-200">
            <input
              type="text"
              placeholder="搜索英文或中文..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">EN</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500">ZH</th>
                <th className="text-center px-4 py-3 text-xs font-medium text-gray-500 w-20">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((entry) => {
                const isStopped = stopWords.includes(entry.en);
                return (
                  <tr
                    key={entry.en}
                    className={`border-b border-gray-100 ${
                      isStopped ? "bg-red-50" : "hover:bg-gray-50"
                    }`}
                  >
                    <td className={`px-4 py-3 font-mono text-xs ${isStopped ? "text-red-400 line-through" : "text-gray-700"}`}>
                      {entry.en}
                    </td>
                    <td className={`px-4 py-3 text-xs ${isStopped ? "text-red-400 line-through" : "text-gray-600"}`}>
                      {entry.zh}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <button
                        onClick={() => toggleStopWord(entry.en)}
                        className={`text-xs px-2 py-1 rounded transition-colors ${
                          isStopped
                            ? "bg-red-100 text-red-600 hover:bg-red-200"
                            : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                        }`}
                      >
                        {isStopped ? "恢复" : "停用"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Stop Words Sidebar */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">停用词</h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (newStopWord.trim()) {
                addStopWord(newStopWord.trim());
                setNewStopWord("");
              }
            }}
            className="flex gap-2 mb-3"
          >
            <input
              type="text"
              placeholder="添加停用词..."
              value={newStopWord}
              onChange={(e) => setNewStopWord(e.target.value)}
              className="flex-1 px-2 py-1.5 border border-gray-300 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
            <button
              type="submit"
              className="px-3 py-1.5 bg-gray-700 text-white text-xs rounded-lg hover:bg-gray-800"
            >
              添加
            </button>
          </form>
          <div className="space-y-1.5 max-h-[500px] overflow-y-auto">
            {stopWords.length === 0 && (
              <p className="text-xs text-gray-400">暂无停用词</p>
            )}
            {stopWords.map((word) => (
              <div
                key={word}
                className="flex items-center justify-between bg-red-50 px-2.5 py-1.5 rounded-lg"
              >
                <span className="text-xs text-red-700 font-mono truncate">{word}</span>
                <button
                  onClick={() => removeStopWord(word)}
                  className="text-red-400 hover:text-red-600 text-xs ml-2 shrink-0"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
