import { type DragEvent, useRef, useState } from "react";

interface Props {
  onLoad: (data: unknown, fileName: string) => void;
  acceptLabel: string;
  icon?: string;
}

export default function FileDropzone({ onLoad, acceptLabel, icon = "📄" }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [loaded, setLoaded] = useState<string | null>(null);

  const handleFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = JSON.parse(e.target?.result as string);
        onLoad(data, file.name);
        setLoaded(file.name);
      } catch {
        alert("JSON 解析失败");
      }
    };
    reader.readAsText(file);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const onDragLeave = () => setDragging(false);

  return (
    <div
      className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
        dragging
          ? "border-blue-400 bg-blue-50"
          : loaded
            ? "border-green-400 bg-green-50"
            : "border-gray-300 hover:border-blue-300 hover:bg-gray-50"
      }`}
      onClick={() => inputRef.current?.click()}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
        }}
      />
      <div className="text-3xl mb-2">{loaded ? "✅" : icon}</div>
      <p className="text-sm text-gray-600">
        {loaded ? (
          <span className="text-green-700 font-medium">{loaded}</span>
        ) : (
          <>
            拖拽或点击选择 <span className="font-mono text-blue-600">{acceptLabel}</span>
          </>
        )}
      </p>
    </div>
  );
}
