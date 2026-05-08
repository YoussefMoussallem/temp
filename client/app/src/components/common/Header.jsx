import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, ChevronRight, Home, LogOut } from "lucide-react";
import { useAuth } from "frontend-comps";
import ExportDeckButton from "../deck/ExportDeckButton";
import ExportDeckDomButton from "../deck/ExportDeckDomButton";

export default function Header({
  chatOpen,
  onToggleChat,
  slidesOpen,
  onToggleSlides,
  activeProjectName,
  onBackToProjects,
}) {
  // ``signOut`` clears MSAL state. The auth-watchdog effect in App.jsx
  // observes the resulting ``isAuthenticated`` flip and navigates to
  // ``/login`` — we don't navigate from here, so all redirect logic
  // lives in one place.
  const { user, signOut } = useAuth();
  const userName = user?.name ?? user?.username ?? "";
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
            Strategy&amp;
          </span>
        </div>
      </div>

      {activeProjectName && (
        <>
          <ChevronRight size={12} className="text-gray-300 mx-3" />
          <button
            onClick={onBackToProjects}
            className="group flex items-center gap-1.5 h-7 px-2 rounded-md text-[12px] font-medium text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer"
            title="Back to projects"
          >
            <Home size={11} className="text-gray-400 group-hover:text-brand transition-colors" />
            <span className="truncate max-w-[220px]">{activeProjectName}</span>
          </button>
        </>
      )}

      <div className="ml-auto flex items-center gap-1">
        {activeProjectName && (
          <>
            <ExportDeckButton />
            <ExportDeckDomButton />

            <span className="w-px h-5 bg-gray-200 mx-1" aria-hidden />

            <button
              onClick={onToggleSlides}
              title={slidesOpen ? "Hide slides" : "Show slides"}
              className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-[11px] font-medium
                         text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors cursor-pointer"
            >
              {slidesOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
              <span className="hidden sm:inline">Slides</span>
            </button>

            <button
              onClick={onToggleChat}
              title={chatOpen ? "Hide chat" : "Show chat"}
              className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-[11px] font-medium
                         text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors cursor-pointer"
            >
              {chatOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
              <span className="hidden sm:inline">Chat</span>
            </button>

            <span className="w-px h-5 bg-gray-200 mx-1" aria-hidden />
          </>
        )}

        {userName && (
          <span className="text-[11px] text-gray-400 hidden sm:block mr-1">{userName}</span>
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
