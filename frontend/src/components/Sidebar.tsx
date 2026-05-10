import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "首页", icon: "🏠" },
  { to: "/review", label: "审校", icon: "📋" },
  { to: "/glossary", label: "术语", icon: "📖" },
  { to: "/logs", label: "日志", icon: "📊" },
  { to: "/translate", label: "翻译", icon: "🌐" },
];

export default function Sidebar() {
  return (
    <aside className="w-56 bg-gray-900 text-white flex flex-col shrink-0">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-sm font-bold tracking-wide">审校工具</h1>
        <p className="text-xs text-gray-400 mt-1">Minecraft Mod Translate</p>
      </div>
      <nav className="flex-1 p-2 space-y-1">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-blue-600 text-white"
                  : "text-gray-300 hover:bg-gray-800 hover:text-white"
              }`
            }
          >
            <span>{link.icon}</span>
            <span>{link.label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
