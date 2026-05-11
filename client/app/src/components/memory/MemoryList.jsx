import { useState } from "react";
import { Plus, BookText, Folder, User } from "lucide-react";
import MemoryCard from "./MemoryCard";
import MemoryComposer from "./MemoryComposer";
import Skeleton from "../common/Skeleton";

/**
 * One scope's memory body — list of friendly cards + AI composer.
 *
 * "Create" goes through ``onCreateFromText`` (LLM structures the input
 * invisibly). "Edit" on a card uses ``onUpsert`` directly (no AI —
 * the inline edit is for fine-tuning what the AI already produced).
 *
 * ``disabledReason`` is for the project-scope case when no project is
 * active. Lets the surface still be discoverable while explaining why
 * it can't be used right now.
 */
export default function MemoryList({
  scope,
  memories,
  loading,
  error,
  onCreateFromText,
  onUpsert,
  onDelete,
  disabledReason = null,
}) {
  const [composing, setComposing] = useState(false);

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
    await onCreateFromText(text);
    setComposing(false);
  };

  return (
    <div className="flex flex-col gap-3">
      {composing ? (
        <MemoryComposer
          scope={scope}
          onCreate={handleCreate}
          onCancel={() => setComposing(false)}
        />
      ) : (
        <button
          type="button"
          onClick={() => setComposing(true)}
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
          {memories.map((m) => (
            <MemoryCard
              key={m.slug}
              memory={m}
              onUpsert={onUpsert}
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
      <p className="text-[11px] text-gray-500 leading-relaxed max-w-[320px]">
        {message}
      </p>
    </div>
  );
}
