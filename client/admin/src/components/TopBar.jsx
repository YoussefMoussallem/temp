import { useAuth } from "frontend-comps";
import { LogOut } from "lucide-react";

export default function TopBar() {
  const { user, signOut } = useAuth();
  const name = user?.name ?? user?.username ?? "";

  return (
    <header className="flex items-center h-12 px-5 bg-white/80 backdrop-blur-md border-b border-gray-200/60 shrink-0">
      <div className="flex items-center gap-2.5">
        <div className="w-6 h-6 rounded-md bg-brand flex items-center justify-center">
          <span className="text-white text-[10px] font-bold font-[var(--font-heading)]">E</span>
        </div>
        <div className="flex items-baseline gap-1.5">
          <h1 className="text-[14px] font-bold tracking-tight text-black font-[var(--font-heading)]">
            Edwin
          </h1>
          <span className="text-[8px] font-semibold uppercase tracking-[2px] text-gray-400">
            Admin
          </span>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-3">
        {name && (
          <span className="text-[11px] text-gray-400 hidden sm:block">{name}</span>
        )}
        <button
          onClick={signOut}
          title="Sign out"
          className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-[11px] font-medium
                     text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors cursor-pointer"
        >
          <LogOut size={14} />
          <span className="hidden sm:inline">Sign out</span>
        </button>
      </div>
    </header>
  );
}
