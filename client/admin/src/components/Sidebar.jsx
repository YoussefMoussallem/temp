import { NavLink } from "react-router-dom";
import { LayoutDashboard, Users, Activity, Folder, Cpu } from "lucide-react";

const NAV = [
  { to: "/",         label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/users",    label: "Users",     icon: Users },
  { to: "/projects", label: "Projects",  icon: Folder },
  { to: "/usage",    label: "Usage",     icon: Activity },
  { to: "/models",   label: "Models",    icon: Cpu },
];

export default function Sidebar() {
  return (
    <nav className="w-48 shrink-0 bg-white/60 backdrop-blur-sm border-r border-gray-200/60 flex flex-col py-3 gap-0.5 px-2">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 px-3 py-1.5 mb-1">
        Navigation
      </p>
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            `flex items-center gap-2.5 h-8 px-3 rounded-lg text-[12px] font-medium transition-colors cursor-pointer ${
              isActive
                ? "bg-brand/10 text-brand"
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            }`
          }
        >
          <Icon size={14} />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
