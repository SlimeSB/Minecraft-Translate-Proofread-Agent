interface Props {
  label: string;
  value: number;
  color: string;
}

export default function StatCard({ label, value, color }: Props) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 shadow-sm">
      <div className={`w-3 h-3 rounded-full ${color}`} />
      <div>
        <p className="text-2xl font-bold">{value}</p>
        <p className="text-xs text-gray-500">{label}</p>
      </div>
    </div>
  );
}
