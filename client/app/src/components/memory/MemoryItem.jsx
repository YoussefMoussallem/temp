import { useState } from "react";
import { ChevronRight, Pencil, Trash2 } from "lucide-react";

const TYPE_COLOR = {
  user: "text-purple-700 bg-purple-50 ring-purple-100",
  feedback: "text-amber-700 bg-amber-50 ring-amber-100",
  project: "text-blue-700 bg-blue-50 ring-blue-100",
  decision: "text-emerald-700 bg-emerald-50 ring-emerald-100",
  stakeholder: "text-indigo-700 bg-indigo-50 ring-indigo-100",
  reference: "text-gray-600 bg-gray-100 ring-gray-200",
};

function TypeChip({ type }) {
  const cls = TYPE_COLOR[type] ?? TYPE_COLOR.reference;
  return (
    <span
      className={`inline-flex items-center text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ring-1 ${cls}`}
    >
      {type}
    </span>
  );
}

/**
 * Collapsed-by-default row for one memory entry.
 *
 * Click the slug to expand and reveal the body + edit/delete actions.
 * Edit goes to ``onEdit`` (the parent renders the form inline). Delete
 * routes through a small inline confirm — irreversible action.
 */
export default function MemoryItem({ memory, onEdit, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  return (
    <div className="rounded-lg ring-1 ring-gray-200/70 bg-white">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors cursor-pointer rounded-lg"
      >
        <ChevronRight
          size={12}
          className={`text-gray-400 transition-transform shrink-0 ${
            expanded ? "rotate-90" : ""
          }`}
        />
        <TypeChip type={memory.type} />
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-[12px] font-semibold text-gray-800 truncate">
            {memory.name}
          </span>
          <span className="text-[10px] text-gray-400 truncate">
            [{memory.slug}] — {memory.description}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-gray-100">
          <pre className="text-[11px] font-mono text-gray-600 whitespace-pre-wrap leading-relaxed bg-gray-50/60 rounded-md p-2 max-h-64 overflow-y-auto">
            {memory.body}
          </pre>

          {confirmingDelete ? (
            <div className="mt-2 flex items-center justify-between gap-2 px-2 py-1.5 rounded-md bg-red-50 border border-red-100">
              <span className="text-[11px] text-red-700">
                Delete <code className="font-mono">{memory.slug}</code>?
              </span>
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(false)}
                  className="text-[10px] px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-white transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setConfirmingDelete(false);
                    onDelete?.(memory.slug);
                  }}
                  className="text-[10px] font-medium px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700 transition-colors cursor-pointer"
                >
                  Delete
                </button>
              </div>
            </div>
          ) : (
            <div className="mt-2 flex justify-end gap-1.5">
              <button
                type="button"
                onClick={() => onEdit?.(memory)}
                className="text-[10px] font-medium px-2 py-1 rounded-md text-gray-600 hover:bg-gray-100 transition-colors cursor-pointer inline-flex items-center gap-1"
              >
                <Pencil size={10} />
                Edit
              </button>
              <button
                type="button"
                onClick={() => setConfirmingDelete(true)}
                className="text-[10px] font-medium px-2 py-1 rounded-md text-red-600 hover:bg-red-50 transition-colors cursor-pointer inline-flex items-center gap-1"
              >
                <Trash2 size={10} />
                Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
