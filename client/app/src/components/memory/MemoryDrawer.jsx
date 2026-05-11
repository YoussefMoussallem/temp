import { X, User, Folder } from "lucide-react";
import { useMemories } from "../../hooks/useMemories";
import MemoryList from "./MemoryList";

/**
 * Single-scope memory drawer. Phase 3.5 split the unified-tabs drawer
 * into two surfaces — one per scope — because users were confusing
 * "About me" with "About this project". Now each lives in its own
 * location (header / chat panel) and renders independently.
 *
 * Props:
 *   - ``scope``       — "user" or "project"
 *   - ``scopeId``     — caller's azure_oid (user) or project_id (project)
 *   - ``projectName`` — optional, only used for scope="project" framing
 */
export default function MemoryDrawer({
  open,
  onClose,
  getToken,
  scope,
  scopeId,
  projectName = null,
}) {
  const { memories, loading, error, createFromText, upsert, remove } =
    useMemories(getToken, { scope, scopeId });

  if (!open) return null;

  const isUser = scope === "user";
  const Icon = isUser ? User : Folder;
  const title = isUser ? "About you" : "About this project";
  const subtitle = isUser
    ? "Things I'll remember across every conversation."
    : projectName
      ? `Things I'll remember for "${truncate(projectName, 40)}".`
      : "Things I'll remember for this project.";

  const disabledReason =
    !isUser && !scopeId
      ? "Open a project to view or edit its notes."
      : null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/20 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white w-[460px] max-w-full h-full flex flex-col shadow-2xl shadow-black/10"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between px-5 py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-start gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-brand-dim flex items-center justify-center shrink-0 mt-0.5">
              <Icon size={14} className="text-brand" />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold">{title}</h2>
              <p className="text-[11px] text-gray-500 mt-0.5 leading-relaxed">
                {subtitle}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer shrink-0"
            aria-label="Close"
          >
            <X size={16} className="text-gray-400" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <MemoryList
            scope={scope}
            memories={memories}
            loading={loading}
            error={error}
            onCreateFromText={createFromText}
            onUpsert={upsert}
            onDelete={remove}
            disabledReason={disabledReason}
          />
        </div>
      </div>
    </div>
  );
}

function truncate(s, n) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
