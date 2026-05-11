import { useState } from "react";
import { Plus, BookText } from "lucide-react";
import MemoryItem from "./MemoryItem";
import MemoryEditor from "./MemoryEditor";
import Skeleton from "../common/Skeleton";

/**
 * One scope's memory tab body — list of entries + "New" affordance +
 * inline editor for create/edit.
 *
 * Disabled state (``disabledReason`` non-null) is for the project tab
 * when no project is active — the tab is reachable but unusable.
 */
export default function MemoryList({
  scope,
  memories,
  loading,
  error,
  onUpsert,
  onDelete,
  disabledReason = null,
}) {
  // editorState: { mode: "new" | "edit", memory?: existingMemory } | null
  const [editorState, setEditorState] = useState(null);

  if (disabledReason) {
    return (
      <EmptyState
        icon={BookText}
        title="Project memory unavailable"
        message={disabledReason}
      />
    );
  }

  const handleSave = async (payload) => {
    await onUpsert(payload);
    setEditorState(null);
  };

  return (
    <div className="flex flex-col gap-3">
      {!editorState && (
        <button
          type="button"
          onClick={() => setEditorState({ mode: "new" })}
          className="self-start inline-flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-dashed border-gray-300 text-gray-600 hover:border-brand hover:text-brand transition-colors cursor-pointer"
        >
          <Plus size={12} />
          New memory
        </button>
      )}

      {editorState && (
        <MemoryEditor
          scope={scope}
          existing={editorState.mode === "edit" ? editorState.memory : null}
          onSave={handleSave}
          onCancel={() => setEditorState(null)}
        />
      )}

      {error && (
        <div className="text-[11px] text-red-600 bg-red-50 border border-red-100 rounded-md px-3 py-2">
          {error}
        </div>
      )}

      {loading && memories.length === 0 && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full rounded-lg" />
          ))}
        </div>
      )}

      {!loading && memories.length === 0 && !editorState && (
        <EmptyState
          icon={BookText}
          title={
            scope === "user"
              ? "No user memories yet"
              : "No project memories yet"
          }
          message={
            scope === "user"
              ? "Save preferences, role, or feedback patterns the agent should carry across every conversation."
              : "Save audience, deadline, key message, stakeholders, or references specific to this project."
          }
        />
      )}

      {memories.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {memories.map((m) => (
            <MemoryItem
              key={m.slug}
              memory={m}
              onEdit={(mem) => setEditorState({ mode: "edit", memory: mem })}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function EmptyState({ icon: Icon, title, message }) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-10 rounded-xl border border-dashed border-gray-200 bg-gray-50/40">
      <div className="w-10 h-10 rounded-2xl bg-white ring-1 ring-gray-200 flex items-center justify-center mb-3">
        <Icon size={18} className="text-gray-400" />
      </div>
      <p className="text-[12px] font-semibold text-gray-700 mb-1">{title}</p>
      <p className="text-[11px] text-gray-500 leading-relaxed max-w-[300px]">
        {message}
      </p>
    </div>
  );
}
