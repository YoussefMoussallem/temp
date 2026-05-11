import { useEffect, useState } from "react";
import { X, User, Folder } from "lucide-react";
import { useMemories } from "../../hooks/useMemories";
import MemoryList from "./MemoryList";

/**
 * Side drawer for memory management. Two scopes share one surface:
 *
 *   [About me]  — user_memories, follows the user across conversations
 *   [This project] — project_memories, scoped to the active deck
 *
 * The project tab is rendered but disabled when there's no active
 * project — gives the user a discoverable "this exists" surface from
 * any screen without forcing a project to be open.
 *
 * Slide-from-right transform mirrors the existing ShareProjectDialog
 * pattern (z-50, backdrop blur, click-outside-to-close).
 */
export default function MemoryDrawer({
  open,
  onClose,
  getToken,
  currentUserOid,
  activeProjectId,
  activeProjectName = null,
}) {
  // Tab defaults to project if one is active (probably what brought
  // the user here); otherwise user.
  const [tab, setTab] = useState(activeProjectId ? "project" : "user");

  // If the active project changes while the drawer is open, snap to
  // its tab so the user doesn't see stale data for a different deck.
  useEffect(() => {
    if (open && activeProjectId) setTab("project");
  }, [open, activeProjectId]);

  const userMem = useMemories(getToken, {
    scope: "user",
    scopeId: currentUserOid,
  });
  const projectMem = useMemories(getToken, {
    scope: "project",
    scopeId: activeProjectId,
  });

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/20 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white w-[460px] max-w-full h-full flex flex-col shadow-2xl shadow-black/10"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-gray-100 shrink-0">
          <div>
            <h2 className="text-sm font-semibold">Memory</h2>
            <p className="text-[11px] text-gray-500 mt-0.5">
              Facts the agent carries between turns and across conversations.
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer"
            aria-label="Close memory drawer"
          >
            <X size={16} className="text-gray-400" />
          </button>
        </header>

        <div className="flex gap-1 px-5 pt-3 border-b border-gray-100 shrink-0">
          <TabButton
            active={tab === "user"}
            onClick={() => setTab("user")}
            icon={User}
            label="About me"
            count={userMem.memories.length}
          />
          <TabButton
            active={tab === "project"}
            onClick={() => setTab("project")}
            icon={Folder}
            label={
              activeProjectName
                ? `This project · ${truncate(activeProjectName, 18)}`
                : "This project"
            }
            count={activeProjectId ? projectMem.memories.length : null}
            dimmed={!activeProjectId}
          />
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {tab === "user" ? (
            <MemoryList
              scope="user"
              memories={userMem.memories}
              loading={userMem.loading}
              error={userMem.error}
              onUpsert={userMem.upsert}
              onDelete={userMem.remove}
            />
          ) : (
            <MemoryList
              scope="project"
              memories={projectMem.memories}
              loading={projectMem.loading}
              error={projectMem.error}
              onUpsert={projectMem.upsert}
              onDelete={projectMem.remove}
              disabledReason={
                activeProjectId
                  ? null
                  : "Open a project to view or edit its memories."
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}

function TabButton({ active, onClick, icon: Icon, label, count, dimmed = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative inline-flex items-center gap-1.5 px-3 py-2 text-[11px] font-semibold border-b-2 transition-colors cursor-pointer ${
        active
          ? "border-brand text-brand"
          : "border-transparent text-gray-500 hover:text-gray-700"
      } ${dimmed ? "opacity-60" : ""}`}
    >
      <Icon size={12} />
      <span>{label}</span>
      {typeof count === "number" && (
        <span
          className={`ml-1 text-[9px] font-bold px-1.5 py-0.5 rounded-full ${
            active ? "bg-brand-dim text-brand" : "bg-gray-100 text-gray-500"
          }`}
        >
          {count}
        </span>
      )}
    </button>
  );
}

function truncate(s, n) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
