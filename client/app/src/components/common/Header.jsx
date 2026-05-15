import { ChevronRight, Home, LogOut, User, BookOpen, Layers } from "lucide-react";
import { useAuth } from "frontend-comps";
import ExportDeckButton from "../deck/ExportDeckButton";
import ExportDeckDomButton from "../deck/ExportDeckDomButton";

/**
 * Top header.
 *
 *   Left  — brand
 *           breadcrumb: project name + "Project memory" link (when in
 *           a project; the link goes to the project's memory page).
 *   Right — exports (project only), "Your memory" link (always
 *           available), user identity, sign-out.
 *
 * Slide / chat panel toggles live inside the panels themselves, not
 * here (Phase 3.5).
 */
export default function Header({
  activeProjectName,
  onBackToProjects,
  onOpenUserMemory,
  onOpenProjectMemory,
  onOpenMasters,
  // Export buttons depend on DeckProvider — render them only when
  // we know we're inside it (chat page yes; masters / memory pages no).
  showDeckActions = true,
}) {
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
          {onOpenProjectMemory && (
            <button
              onClick={onOpenProjectMemory}
              title="Project memory — what I remember about this deck"
              className="ml-1 inline-flex items-center gap-1 h-7 px-2 rounded-md text-[11px] font-medium text-gray-500 hover:bg-brand-dim hover:text-brand transition-colors cursor-pointer"
            >
              <BookOpen size={11} />
              <span>Project memory</span>
            </button>
          )}
          {onOpenMasters && (
            <button
              onClick={onOpenMasters}
              title="Master templates — manage the PowerPoint templates this deck inherits from"
              className="ml-1 inline-flex items-center gap-1 h-7 px-2 rounded-md text-[11px] font-medium text-gray-500 hover:bg-brand-dim hover:text-brand transition-colors cursor-pointer"
            >
              <Layers size={11} />
              <span>Masters</span>
            </button>
          )}
        </>
      )}

      <div className="ml-auto flex items-center gap-1">
        {activeProjectName && showDeckActions && (
          <>
            <ExportDeckButton />
            <ExportDeckDomButton />
            <span className="w-px h-5 bg-gray-200 mx-1" aria-hidden />
          </>
        )}

        {onOpenUserMemory && (
          <button
            onClick={onOpenUserMemory}
            title="Your memory — what I remember about you across every conversation"
            className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-[11px] font-medium
                       text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors cursor-pointer"
          >
            <User size={14} />
            <span className="hidden sm:inline">Your memory</span>
          </button>
        )}

        {userName && (
          <span className="text-[11px] text-gray-400 hidden sm:block mx-1">{userName}</span>
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
