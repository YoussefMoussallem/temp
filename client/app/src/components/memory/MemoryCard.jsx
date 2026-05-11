import { useState } from "react";
import { ChevronRight, Pencil, Trash2, X } from "lucide-react";

// Friendly category labels — the persisted "type" field is technical;
// surface a consultant-readable label on the card. Falls back to the
// raw type when we don't have a mapping.
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
 *   - Category badge, title, one-line summary
 *   - Click to expand the full body
 *   - Hover reveals edit + delete controls
 *
 * Edit mode is NOT handled inline anymore — the parent swaps the card
 * out for a MemoryComposer pre-filled with the body. That keeps the
 * AI structuring as the single edit path (matches create) so the user
 * doesn't see slug/type/name/description as separate fields.
 *
 * Slug + type are intentionally never shown to the user — they're
 * internal handles the agent uses to address entries.
 */
export default function MemoryCard({ memory, onEdit, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  return (
    <div className="group/card rounded-xl ring-1 ring-gray-200/70 bg-white hover:ring-gray-300 transition-shadow">
      {/* Header row — title + summary + chevron + hover-revealed actions */}
      <div className="flex items-start gap-2 px-3 py-2.5">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="shrink-0 mt-0.5"
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          <ChevronRight
            size={12}
            className={`text-gray-400 transition-transform ${expanded ? "rotate-90" : ""}`}
          />
        </button>

        <div className="flex flex-col gap-1 min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <CategoryBadge type={memory.type} />
          </div>

          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-[12px] font-semibold text-gray-800 text-left hover:text-brand transition-colors cursor-pointer leading-snug"
          >
            {memory.name}
          </button>

          <p className="text-[11px] text-gray-500 leading-snug">
            {memory.description}
          </p>
        </div>

        {!confirmingDelete && (
          <div className="opacity-0 group-hover/card:opacity-100 transition-opacity flex gap-0.5 shrink-0">
            <button
              type="button"
              onClick={() => onEdit?.(memory)}
              title="Edit with AI"
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

      {/* Expanded body — read-only preview. Editing goes through the
          AI composer (parent renders) so the read view here is just a
          dump of the body markdown. */}
      {expanded && (
        <div className="px-3 pb-3 border-t border-gray-100 pt-2">
          <pre className="text-[11px] font-mono text-gray-600 whitespace-pre-wrap leading-relaxed bg-gray-50/60 rounded-md p-2 max-h-64 overflow-y-auto">
            {memory.body}
          </pre>
        </div>
      )}
    </div>
  );
}
