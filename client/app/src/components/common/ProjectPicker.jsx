import { useState } from "react";
import { FolderPlus, Folder, Trash2, UserPlus, Users, Loader2, Pencil } from "lucide-react";
import Skeleton from "./Skeleton";

/**
 * PowerPoint-style backstage / start screen.
 *
 * Shown when no project is selected. Left column: "New" (create a blank
 * project). Right column: two stacked sections — "Your projects" (owner
 * role) and "Shared with you" (editor / viewer role). Both keep
 * most-recently-updated-first ordering inherited from the backend.
 * Clicking a project opens the main app.
 *
 * Role-aware affordances on each card:
 * - Shared cards show a small role pill (EDITOR / VIEWER).
 * - Owners see a Share button on hover (opens ShareProjectDialog).
 * - The Delete button is owner-only.
 */
function ProjectCard({ project: p, onOpen, onDelete, onRename, onShare }) {
  // Track in-flight delete so we can disable the row + show a spinner
  // instead of letting the user click again or wonder if the click took.
  // Local state because the parent doesn't tell us per-row status; the
  // remove() call is awaited here.
  const [deleting, setDeleting] = useState(false);
  // Rename: inline edit. ``editing`` swaps the name span for an input,
  // ``renaming`` shows a small spinner during the API call. Both kept
  // in this card's local state — sibling cards aren't affected.
  const [editing, setEditing] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(p.name);
  const updated = new Date(p.updated_at);
  const dateLabel = updated.toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
  const isOwner = p.role === "owner";
  const isShared = p.role && p.role !== "owner";
  const canRename = isOwner && typeof onRename === "function";

  const handleDelete = async (e) => {
    e.stopPropagation();
    if (deleting) return;
    if (!confirm(`Delete "${p.name}"? All conversations will be lost.`)) return;
    setDeleting(true);
    try {
      await onDelete(p.id);
      // No need to clear `deleting` on success — the row unmounts.
    } catch {
      setDeleting(false);
    }
  };

  const startEdit = (e) => {
    e.stopPropagation();
    setDraftName(p.name);
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setDraftName(p.name);
  };

  const submitRename = async () => {
    const trimmed = draftName.trim();
    if (!trimmed) {
      cancelEdit();
      return;
    }
    if (trimmed === p.name) {
      cancelEdit();
      return;
    }
    setRenaming(true);
    try {
      await onRename(p.id, trimmed);
      setEditing(false);
    } catch {
      // Keep the editor open with the user's draft so they can retry.
    } finally {
      setRenaming(false);
    }
  };

  const onCardClick = () => {
    if (deleting || editing) return;
    onOpen(p.id);
  };

  return (
    <div
      onClick={onCardClick}
      aria-busy={deleting}
      className={`group relative flex items-center gap-3 p-4 rounded-lg bg-white border border-gray-200 transition-all ${
        deleting
          ? "opacity-60 pointer-events-none"
          : editing
          ? "border-brand shadow-sm cursor-default"
          : "hover:border-brand hover:shadow-sm cursor-pointer"
      }`}
    >
      <div className="w-10 h-10 rounded-md bg-gray-100 flex items-center justify-center shrink-0 group-hover:bg-brand/10 transition-colors">
        <Folder size={18} className="text-gray-500 group-hover:text-brand transition-colors" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          {editing ? (
            <input
              autoFocus
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  submitRename();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  cancelEdit();
                }
              }}
              onBlur={submitRename}
              disabled={renaming}
              className="text-[13px] font-semibold text-gray-900 bg-white px-1.5 py-0.5 -my-0.5 -mx-1.5 rounded border border-brand focus:outline-none focus:ring-1 focus:ring-brand/40 min-w-0 flex-1 disabled:opacity-60"
            />
          ) : (
            <div className="text-[13px] font-semibold text-gray-900 truncate">{p.name}</div>
          )}
          {renaming && (
            <Loader2 size={11} className="animate-spin text-brand shrink-0" />
          )}
          {!editing && isShared && (
            <span
              title={`Shared (${p.role})`}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wider bg-blue-50 text-blue-600"
            >
              <Users size={9} />
              {p.role}
            </span>
          )}
        </div>
        <div className="text-[11px] text-gray-500 truncate mt-0.5">
          {p.description || "No description"}
        </div>
        <div className="text-[10px] text-gray-400 mt-1">{dateLabel}</div>
      </div>
      {canRename && !editing && (
        <button
          type="button"
          onClick={startEdit}
          className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded flex items-center justify-center text-gray-400 hover:text-brand hover:bg-brand/10 transition-all"
          title="Rename project"
        >
          <Pencil size={11} />
        </button>
      )}
      {isOwner && onShare && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onShare(p);
          }}
          className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded flex items-center justify-center text-gray-400 hover:text-brand hover:bg-brand/10 transition-all"
          title="Share project"
        >
          <UserPlus size={12} />
        </button>
      )}
      {isOwner && (
        <button
          type="button"
          onClick={handleDelete}
          disabled={deleting}
          className={`w-6 h-6 rounded flex items-center justify-center transition-all ${
            deleting
              ? "opacity-100 text-red-500"
              : "opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 hover:bg-red-50"
          }`}
          title={deleting ? "Deleting…" : "Delete project"}
        >
          {deleting ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Trash2 size={12} />
          )}
        </button>
      )}
    </div>
  );
}

// Skeleton for the right-pane project list during initial fetch.
// Renders one section header and four card placeholders that match the
// real ProjectCard footprint (icon + two text rows + date) so layout is
// stable when data arrives. Four covers most decks; if there are more,
// the real list overflows naturally on render.
function ProjectListSkeleton() {
  return (
    <div aria-label="Loading projects">
      <Skeleton className="h-3 w-32 mb-3" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 p-4 rounded-lg bg-white border border-gray-200"
          >
            <Skeleton className="w-10 h-10 rounded-md shrink-0" />
            <div className="flex-1 flex flex-col gap-1.5">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-2.5 w-1/2" />
              <Skeleton className="h-2 w-1/4 mt-0.5" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProjectSection({ title, projects, onOpen, onDelete, onRename, onShare }) {
  if (projects.length === 0) return null;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-500">
          {title}
        </h2>
        <span className="text-[11px] text-gray-400">
          {projects.length} {projects.length === 1 ? "project" : "projects"}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {projects.map((p) => (
          <ProjectCard
            key={p.id}
            project={p}
            onOpen={onOpen}
            onDelete={onDelete}
            onRename={onRename}
            onShare={onShare}
          />
        ))}
      </div>
    </div>
  );
}

export default function ProjectPicker({
  projects,
  loading,
  error,
  onOpen,
  onCreate,
  onDelete,
  onRename,
  onShare,
}) {
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    try {
      const project = await onCreate(trimmed, description.trim() || null);
      if (project) onOpen(project.id);
      setName("");
      setDescription("");
      setCreating(false);
    } finally {
      setSubmitting(false);
    }
  };

  // Split into "Your projects" (owner) vs "Shared with you" (editor /
  // viewer). Backend already orders by ``updated_at DESC`` so we just
  // partition without re-sorting.
  const owned = projects.filter((p) => p.role === "owner");
  const shared = projects.filter((p) => p.role && p.role !== "owner");
  const isEmpty = projects.length === 0;

  return (
    <div className="flex-1 flex overflow-hidden bg-[#f3f2f1]">
      {/* Left: New */}
      <div className="w-[340px] shrink-0 bg-white border-r border-gray-200 p-8 flex flex-col">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-500 mb-4">
          New
        </h2>

        {!creating ? (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="group flex items-start gap-3 p-4 rounded-lg border border-gray-200 hover:border-brand hover:shadow-sm transition-all text-left"
          >
            <div className="w-10 h-10 rounded-md bg-brand/10 flex items-center justify-center shrink-0 group-hover:bg-brand/20 transition-colors">
              <FolderPlus size={18} className="text-brand" />
            </div>
            <div>
              <div className="text-[13px] font-semibold text-gray-900">Blank project</div>
              <div className="text-[11px] text-gray-500 mt-0.5">
                Start a new consulting deck from scratch
              </div>
            </div>
          </button>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-2">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Project name"
              className="text-[13px] px-3 py-2 rounded border border-gray-300 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/30"
            />
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Description (optional)"
              className="text-[12px] px-3 py-2 rounded border border-gray-300 focus:outline-none focus:border-brand focus:ring-1 focus:ring-brand/30"
            />
            <div className="flex gap-2 mt-1">
              <button
                type="submit"
                disabled={!name.trim() || submitting}
                className="flex-1 h-8 rounded bg-brand text-white text-[12px] font-semibold disabled:opacity-40 hover:bg-brand/90 transition-colors flex items-center justify-center gap-1.5"
              >
                {submitting && <Loader2 size={12} className="animate-spin" />}
                {submitting ? "Creating…" : "Create"}
              </button>
              <button
                type="button"
                onClick={() => { setCreating(false); setName(""); setDescription(""); }}
                disabled={submitting}
                className="px-3 h-8 rounded bg-gray-100 text-gray-600 text-[12px] hover:bg-gray-200 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Right: Your projects + Shared with you */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-3xl space-y-8">
          {loading && isEmpty && <ProjectListSkeleton />}

          {!loading && error && isEmpty && (
            <div className="rounded-md border border-red-200 bg-red-50/60 px-4 py-3 text-[12px] text-red-700">
              Couldn't load your projects: {error}
            </div>
          )}

          {!loading && !error && isEmpty && (
            <div className="text-center py-16 text-gray-400">
              <Folder size={32} className="mx-auto mb-3 text-gray-300" />
              <div className="text-[13px]">No projects yet</div>
              <div className="text-[11px] mt-1">Create one to get started</div>
            </div>
          )}

          <ProjectSection
            title="Your projects"
            projects={owned}
            onOpen={onOpen}
            onDelete={onDelete}
            onRename={onRename}
            onShare={onShare}
          />
          <ProjectSection
            title="Shared with you"
            projects={shared}
            onOpen={onOpen}
            onDelete={onDelete}
            onRename={onRename}
            onShare={onShare}
          />
        </div>
      </div>
    </div>
  );
}
