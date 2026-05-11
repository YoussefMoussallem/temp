import { ChevronLeft, User, Folder } from "lucide-react";
import Header from "../components/common/Header";
import MemoryList from "../components/memory/MemoryList";
import { useMemories } from "../hooks/useMemories";

/**
 * Full-screen memory page (Phase 3.5 follow-up).
 *
 * Replaces the earlier drawer surface. Two scopes share this one
 * component, parametric on ``scope``:
 *
 *   - ``user``    — caller's personal memory; visible across every
 *                   conversation, in every project.
 *   - ``project`` — facts tied to one specific deck; visible only when
 *                   inside that project.
 *
 * The page owns its own back affordance and reuses the global Header
 * for identity continuity; it does NOT carry the breadcrumb memory
 * link (you're already on it).
 */
export default function MemoryPage({
  scope,
  scopeId,
  projectName = null,
  onBack,
  getToken,
  onOpenUserMemory,
}) {
  const { memories, loading, error, saveFromText, remove } =
    useMemories(getToken, { scope, scopeId });

  const isUser = scope === "user";
  const Icon = isUser ? User : Folder;
  const title = isUser ? "Your memory" : "Project memory";
  const subtitle = isUser
    ? "Things I'll remember about you across every conversation. Type in plain English — I'll structure it."
    : projectName
      ? `Things I'll remember for "${projectName}". Type in plain English — I'll structure it.`
      : "Things I'll remember for this deck. Type in plain English — I'll structure it.";

  // Don't surface "Your memory" in the header when the user is
  // already on it — would create a no-op visual loop. Likewise omit
  // it when they're on the project page but the implicit user-scope
  // memory access lives only here.
  const headerOnOpenUserMemory = isUser ? null : onOpenUserMemory;

  return (
    <div className="h-screen flex flex-col bg-[#f9f7f5]">
      <Header onOpenUserMemory={headerOnOpenUserMemory} />

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-6 py-6 flex flex-col gap-5">
          <button
            type="button"
            onClick={onBack}
            className="self-start inline-flex items-center gap-1 text-[11px] font-medium text-gray-500 hover:text-brand transition-colors cursor-pointer"
          >
            <ChevronLeft size={13} />
            Back
          </button>

          <header className="flex items-start gap-3 pb-2 border-b border-gray-200/60">
            <div className="w-10 h-10 rounded-xl bg-brand-dim flex items-center justify-center shrink-0">
              <Icon size={18} className="text-brand" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-lg font-semibold text-gray-900 leading-tight">
                {title}
              </h1>
              <p className="text-[12px] text-gray-500 mt-1 leading-relaxed">
                {subtitle}
              </p>
            </div>
          </header>

          <MemoryList
            scope={scope}
            memories={memories}
            loading={loading}
            error={error}
            onSaveFromText={saveFromText}
            onDelete={remove}
            disabledReason={
              !isUser && !scopeId
                ? "Open a project to manage its memory."
                : null
            }
          />
        </div>
      </div>
    </div>
  );
}
