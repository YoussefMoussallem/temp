import { useState } from "react";
import { ChevronRight, Pencil, Trash2, Check, X } from "lucide-react";

// Friendly category labels — the persisted "type" field is technical;
// surface a consultant-readable label on the card. Falls back to title-
// casing the raw type when we don't have a mapping.
const TYPE_LABEL = {
  user: "About you",
  feedback: "Preference",
  reference: "Reference",
  project: "Project fact",
  decision: "Decision",
  stakeholder: "Stakeholder",
};

const TYPE_COLOR = {
  user: "bg-purple-50 text-purple-700 ring-purple-100",
  feedback: "bg-amber-50 text-amber-700 ring-amber-100",
  reference: "bg-gray-100 text-gray-600 ring-gray-200",
  project: "bg-blue-50 text-blue-700 ring-blue-100",
  decision: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  stakeholder: "bg-indigo-50 text-indigo-700 ring-indigo-100",
};

function CategoryBadge({ type }) {
  const label = TYPE_LABEL[type] ?? type;
  const cls = TYPE_COLOR[type] ?? TYPE_COLOR.reference;
  return (
    <span
      className={`inline-flex items-center text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ring-1 ${cls}`}
    >
      {label}
    </span>
  );
}

/**
 * Friendly card view for one memory.
 *
 * View mode (default):
 *   - Category badge, title (``name``), one-line summary (``description``)
 *   - Click card to expand the full body
 *   - Hover reveals edit + delete controls
 *
 * Inline edit mode (after the user clicks Edit):
 *   - Title and summary become editable text inputs
 *   - Direct PUT via ``onUpsert`` (no AI re-structure for fine-tuning)
 *   - Save / Cancel buttons
 *
 * Slug + type are intentionally never shown — they're internal handles
 * the agent uses to address entries; surfacing them would only confuse
 * a non-technical user.
 */
export default function MemoryCard({ memory, onUpsert, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // Drafts for inline edit mode.
  const [draftName, setDraftName] = useState(memory.name);
  const [draftDescription, setDraftDescription] = useState(memory.description);
  const [draftBody, setDraftBody] = useState(memory.body);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const enterEdit = () => {
    setDraftName(memory.name);
    setDraftDescription(memory.description);
    setDraftBody(memory.body);
    setError(null);
    setEditing(true);
    setExpanded(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setError(null);
  };

  const handleSave = async () => {
    const name = draftName.trim();
    const description = draftDescription.trim();
    const body = draftBody.trim();
    if (!name) {
      setError("Title is required.");
      return;
    }
    if (!description) {
      setError("Summary is required.");
      return;
    }
    if (description.length > 150) {
      setError("Summary must be ≤ 150 characters.");
      return;
    }
    if (!body) {
      setError("Body is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Direct upsert with the same slug + type — title / summary /
      // body all editable. Slug stays the addressable handle so the
      // entry doesn't fork.
      await onUpsert({
        slug: memory.slug,
        type: memory.type,
        name,
        description,
        body,
      });
      setEditing(false);
    } catch (e) {
      setError(e?.message ?? "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="group/card rounded-xl ring-1 ring-gray-200/70 bg-white hover:ring-gray-300 transition-shadow">
      {/* Header row — title + summary + chevron + hover-revealed actions */}
      <div className="flex items-start gap-2 px-3 py-2.5">
        <button
          type="button"
          onClick={() => !editing && setExpanded((v) => !v)}
          disabled={editing}
          className="shrink-0 mt-0.5"
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          <ChevronRight
            size={12}
            className={`text-gray-400 transition-transform ${expanded ? "rotate-90" : ""} ${editing ? "opacity-40" : ""}`}
          />
        </button>

        <div className="flex flex-col gap-1 min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <CategoryBadge type={memory.type} />
          </div>

          {editing ? (
            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-medium uppercase tracking-wide text-gray-400">
                Title
              </label>
              <input
                type="text"
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                maxLength={120}
                placeholder="Short title — what is this memory about?"
                className="text-[13px] font-semibold text-gray-800 border border-gray-200 rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand"
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="text-[12px] font-semibold text-gray-800 text-left hover:text-brand transition-colors cursor-pointer leading-snug"
            >
              {memory.name}
            </button>
          )}

          {editing ? (
            <div className="flex flex-col gap-1 mt-1">
              <div className="flex items-baseline justify-between">
                <label className="text-[10px] font-medium uppercase tracking-wide text-gray-400">
                  Summary (the one-line I show in lists)
                </label>
                <span
                  className={`text-[10px] ${
                    draftDescription.length > 150
                      ? "text-red-600"
                      : "text-gray-400"
                  }`}
                >
                  {draftDescription.length}/150
                </span>
              </div>
              <textarea
                value={draftDescription}
                onChange={(e) => setDraftDescription(e.target.value)}
                maxLength={150}
                rows={2}
                placeholder="A concrete one-liner so I know when this is relevant."
                className="text-[12px] text-gray-700 border border-gray-200 rounded-md px-3 py-2 resize-y min-h-[48px] leading-relaxed focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand"
              />
            </div>
          ) : (
            <p className="text-[11px] text-gray-500 leading-snug">
              {memory.description}
            </p>
          )}

          {editing && (
            <div className="flex flex-col gap-1 mt-2">
              <label className="text-[10px] font-medium uppercase tracking-wide text-gray-400">
                Full note (the detail behind this memory)
              </label>
              <textarea
                value={draftBody}
                onChange={(e) => setDraftBody(e.target.value)}
                rows={8}
                placeholder="The full content. Plain prose or markdown."
                className="text-[12px] font-mono text-gray-700 border border-gray-200 rounded-md px-3 py-2 resize-y min-h-[180px] leading-relaxed focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand"
              />
            </div>
          )}
        </div>

        {!editing && !confirmingDelete && (
          <div className="opacity-0 group-hover/card:opacity-100 transition-opacity flex gap-0.5 shrink-0">
            <button
              type="button"
              onClick={enterEdit}
              title="Edit"
              className="w-6 h-6 rounded-md hover:bg-gray-100 flex items-center justify-center cursor-pointer text-gray-500"
            >
              <Pencil size={11} />
            </button>
            <button
              type="button"
              onClick={() => setConfirmingDelete(true)}
              title="Forget this"
              className="w-6 h-6 rounded-md hover:bg-red-50 hover:text-red-600 flex items-center justify-center cursor-pointer text-gray-500"
            >
              <Trash2 size={11} />
            </button>
          </div>
        )}
      </div>

      {/* Edit footer — save / cancel */}
      {editing && (
        <div className="px-3 pb-3 border-t border-gray-100 pt-2 flex items-center gap-2 justify-end">
          {error && (
            <span className="text-[10px] text-red-600 mr-auto">{error}</span>
          )}
          <button
            type="button"
            onClick={cancelEdit}
            disabled={saving}
            className="text-[11px] font-medium px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="text-[11px] font-medium px-2.5 py-1 rounded-md bg-brand text-white hover:bg-brand/90 cursor-pointer inline-flex items-center gap-1 disabled:opacity-60"
          >
            <Check size={11} />
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      )}

      {/* Delete confirm */}
      {confirmingDelete && (
        <div className="px-3 pb-3 border-t border-gray-100 pt-2 flex items-center justify-between gap-2">
          <span className="text-[11px] text-red-700">
            Forget this memory? This can't be undone.
          </span>
          <div className="flex gap-1.5 shrink-0">
            <button
              type="button"
              onClick={() => setConfirmingDelete(false)}
              className="text-[10px] px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50 cursor-pointer"
            >
              Keep
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirmingDelete(false);
                onDelete?.(memory.slug);
              }}
              className="text-[10px] font-medium px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700 cursor-pointer inline-flex items-center gap-1"
            >
              <X size={10} />
              Forget
            </button>
          </div>
        </div>
      )}

      {/* Expanded body */}
      {expanded && !editing && (
        <div className="px-3 pb-3 border-t border-gray-100 pt-2">
          <pre className="text-[11px] font-mono text-gray-600 whitespace-pre-wrap leading-relaxed bg-gray-50/60 rounded-md p-2 max-h-64 overflow-y-auto">
            {memory.body}
          </pre>
        </div>
      )}
    </div>
  );
}
