import { useState } from "react";
import { Plus, BookText, Folder, User } from "lucide-react";
import MemoryCard from "./MemoryCard";
import MemoryComposer from "./MemoryComposer";
import Skeleton from "../common/Skeleton";

/**
 * One scope's memory body — friendly cards + AI-driven composer.
 *
 * Two composer mount points:
 *   - Top of the list when ``composing === true`` (new entry)
 *   - In-place of a card when ``editingSlug === <slug>`` (edit existing)
 *
 * Both feed through ``onSaveFromText(text, slug?)`` — passing the
 * slug makes the backend force-preserve it so the upsert overwrites.
 * Omitting it lets the LLM pick (create flow).
 *
 * ``disabledReason`` is the project-scope no-active-project case.
 */
export default function MemoryList({
  scope,
  memories,
  loading,
  error,
  onSaveFromText,
  onDelete,
  disabledReason = null,
}) {
  const [composing, setComposing] = useState(false);
  const [editingSlug, setEditingSlug] = useState(null);

  if (disabledReason) {
    return (
      <EmptyState
        icon={Folder}
        title="Project memory unavailable"
        message={disabledReason}
      />
    );
  }

  const handleCreate = async (text) => {
    await onSaveFromText(text);
    setComposing(false);
  };

  const handleEdit = async (text) => {
    if (!editingSlug) return;
    await onSaveFromText(text, editingSlug);
    setEditingSlug(null);
  };

  return (
    <div className="flex flex-col gap-3">
      {composing ? (
        <MemoryComposer
          scope={scope}
          mode="create"
          onSubmit={handleCreate}
          onCancel={() => setComposing(false)}
        />
      ) : (
        <button
          type="button"
          onClick={() => {
            setComposing(true);
            setEditingSlug(null);
          }}
          className="self-start inline-flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-dashed border-gray-300 text-gray-600 hover:border-brand hover:text-brand transition-colors cursor-pointer"
        >
          <Plus size={12} />
          Remember something
        </button>
      )}

      {error && (
        <div className="text-[11px] text-red-600 bg-red-50 border border-red-100 rounded-md px-3 py-2">
          {error}
        </div>
      )}

      {loading && memories.length === 0 && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-14 w-full rounded-xl" />
          ))}
        </div>
      )}

      {!loading && memories.length === 0 && !composing && (
        <EmptyState
          icon={scope === "user" ? User : BookText}
          title={
            scope === "user" ? "Nothing remembered yet" : "No project notes yet"
          }
          message={
            scope === "user"
              ? "I don't carry anything between conversations yet. Tell me a preference, your role, or how you like to work — I'll keep it across every deck you make."
              : "Tell me about this deck and I'll keep it for next time we work on it: who the audience is, when it's due, the key takeaway, anything decided."
          }
        />
      )}

      {memories.length > 0 && (
        <div className="flex flex-col gap-2">
          {memories.map((m) =>
            editingSlug === m.slug ? (
              <MemoryComposer
                key={m.slug}
                scope={scope}
                mode="edit"
                initialText={m.body}
                onSubmit={handleEdit}
                onCancel={() => setEditingSlug(null)}
              />
            ) : (
              <MemoryCard
                key={m.slug}
                memory={m}
                onEdit={(mem) => {
                  setEditingSlug(mem.slug);
                  setComposing(false);
                }}
                onDelete={onDelete}
              />
            ),
          )}
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
      <p className="text-[11px] text-gray-500 leading-relaxed max-w-[320px]">
        {message}
      </p>
    </div>
  );
}
