import { useEffect, useRef, useState } from "react";
import { ChevronDown, MessageSquare, Plus, Trash2, Loader2 } from "lucide-react";
import Skeleton from "../common/Skeleton";

/**
 * PowerPoint-style "Recent" dropdown for conversations in the active project.
 *
 * Renders a compact trigger button (shows active conversation title) and
 * a floating popover with the full conversation list plus a "+ New" row.
 */
export default function ConversationMenu({
  conversations,
  loading = false,
  error = null,
  activeId,
  onSelect,
  onCreate,
  onDelete,
}) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // Track per-row delete in flight. Map keyed by conversation id so
  // deleting one row doesn't gray out the others.
  const [deletingIds, setDeletingIds] = useState(() => new Set());
  const [title, setTitle] = useState("");
  const wrapperRef = useRef(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => {
      if (!wrapperRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const active = conversations.find((c) => c.id === activeId);
  // While the list is loading we don't yet know if the active id resolves
  // to a real conversation, so show a neutral placeholder instead of
  // flashing "No conversation" briefly on every project switch.
  const label = active
    ? active.title
    : loading
    ? "Loading…"
    : "No conversation";

  const submit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    const t = title.trim() || "New conversation";
    setSubmitting(true);
    try {
      const c = await onCreate(t);
      if (c) onSelect(c.id);
      setTitle("");
      setCreating(false);
      setOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (e, c) => {
    e.stopPropagation();
    if (deletingIds.has(c.id)) return;
    if (!confirm(`Delete conversation "${c.title}"?`)) return;
    setDeletingIds((prev) => {
      const next = new Set(prev);
      next.add(c.id);
      return next;
    });
    try {
      await onDelete(c.id);
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(c.id);
        return next;
      });
    }
  };

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="h-7 px-2.5 rounded-md flex items-center gap-1.5 text-[11px] font-medium text-gray-600 hover:bg-gray-100 transition-colors max-w-[200px]"
        title="Switch conversation"
      >
        <MessageSquare size={12} className="text-gray-400 shrink-0" />
        <span className="truncate">{label}</span>
        <ChevronDown size={11} className="text-gray-400 shrink-0" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-[280px] bg-white border border-gray-200 rounded-md shadow-lg z-50 overflow-hidden">
          {/* New conversation */}
          {!creating ? (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="w-full flex items-center gap-2 px-3 py-2 text-[12px] text-brand hover:bg-brand/5 border-b border-gray-100 transition-colors"
            >
              <Plus size={13} />
              <span className="font-medium">New conversation</span>
            </button>
          ) : (
            <form onSubmit={submit} className="px-3 py-2 border-b border-gray-100 flex items-center gap-2">
              <input
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Escape" && !submitting) { setCreating(false); setTitle(""); } }}
                placeholder="Conversation title"
                disabled={submitting}
                className="flex-1 text-[12px] px-2 py-1 rounded border border-gray-300 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/30 disabled:opacity-60"
              />
              {submitting && (
                <Loader2 size={12} className="animate-spin text-brand shrink-0" />
              )}
            </form>
          )}

          {/* Recent list */}
          <div className="max-h-[320px] overflow-y-auto py-1">
            {loading && conversations.length === 0 && <ConversationListSkeleton />}

            {!loading && error && conversations.length === 0 && (
              <div className="px-3 py-3 text-[11px] text-red-600 text-center">
                Couldn't load conversations.
              </div>
            )}

            {!loading && !error && conversations.length === 0 && (
              <div className="px-3 py-4 text-[11px] text-gray-400 text-center">
                No conversations yet
              </div>
            )}

            {conversations.map((c) => {
              const isActive = c.id === activeId;
              const isDeleting = deletingIds.has(c.id);
              return (
                <div
                  key={c.id}
                  onClick={() => {
                    if (isDeleting) return;
                    onSelect(c.id);
                    setOpen(false);
                  }}
                  aria-busy={isDeleting}
                  className={`group flex items-center gap-2 px-3 py-1.5 text-[12px] transition-colors
                    ${isDeleting ? "opacity-50 pointer-events-none" : "cursor-pointer"}
                    ${isActive ? "bg-brand/5 text-gray-900" : "text-gray-700 hover:bg-gray-50"}`}
                >
                  {isActive && <span className="w-[3px] h-4 rounded bg-brand -ml-2" />}
                  <MessageSquare size={11} className={isActive ? "text-brand" : "text-gray-400"} />
                  <span className="flex-1 truncate">{c.title}</span>
                  {c.message_count > 0 && (
                    <span className={`text-[9px] font-medium tabular-nums ${isActive ? "text-brand" : "text-gray-400"}`}>
                      {c.message_count}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={(e) => handleDelete(e, c)}
                    disabled={isDeleting}
                    className={`w-4 h-4 rounded flex items-center justify-center transition-all ${
                      isDeleting
                        ? "opacity-100 text-red-500"
                        : "opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 hover:bg-red-50"
                    }`}
                    title={isDeleting ? "Deleting…" : "Delete"}
                  >
                    {isDeleting ? (
                      <Loader2 size={10} className="animate-spin" />
                    ) : (
                      <Trash2 size={10} />
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// Three skeleton rows matching the real conversation row footprint
// (icon + title bar + count badge). Sized to match `py-1.5` and the
// `MessageSquare` icon so the popover doesn't jump on data arrival.
function ConversationListSkeleton() {
  return (
    <div aria-label="Loading conversations">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 px-3 py-1.5">
          <Skeleton className="w-2.5 h-2.5 rounded-full shrink-0" />
          <Skeleton className="h-2.5 flex-1" />
        </div>
      ))}
    </div>
  );
}
