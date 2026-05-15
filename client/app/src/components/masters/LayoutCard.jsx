// One layout in the curation grid.
//
// Visual: PNG preview at the top, metadata below. Editable controls
// (kind dropdown, enabled toggle, default star, notes) update via
// optimistic PATCH on the parent hook. Errors bubble to the parent
// page banner.
//
// The dropdown's "Auto" option clears the user override (sends
// user_kind=""); selecting any other value sends user_kind=<v>. We
// don't expose every LayoutKind in the dropdown — only the curated
// set that the agent and renderer actually understand.

import { Star, EyeOff, Eye, AlertCircle } from "lucide-react";

const KIND_OPTIONS = [
  { value: "", label: "Auto" },
  { value: "title", label: "Title / cover" },
  { value: "section_header", label: "Section header" },
  { value: "agenda", label: "Agenda" },
  { value: "content", label: "Content" },
  { value: "two_column", label: "Two columns" },
  { value: "comparison", label: "Comparison" },
  { value: "kpi", label: "KPI / big number" },
  { value: "quote", label: "Quote" },
  { value: "blank", label: "Blank" },
  { value: "other", label: "Other" },
];

export default function LayoutCard({
  layout,
  onPatch,
  onMarkDefault,
  busy,
  repeatCount = 1,
}) {
  const kind = layout.user_kind ?? layout.auto_kind ?? "other";
  const overridden = layout.user_kind != null;
  const enabled = layout.enabled !== false;
  const isDefault = layout.is_default === true;

  const handleKind = (e) => {
    const value = e.target.value;
    // Auto = clear override (sentinel "")
    onPatch({ user_kind: value === "" ? "" : value });
  };

  const handleEnable = () => onPatch({ enabled: !enabled });

  const handleNotesBlur = (e) => {
    const value = e.target.value.trim();
    if (value === (layout.notes ?? "")) return; // no-op
    onPatch({ notes: value === "" ? "__CLEAR__" : value });
  };

  return (
    <li
      className={`bg-white rounded-2xl ring-1 shadow-sm overflow-hidden transition-colors ${
        enabled ? "ring-gray-200/80" : "ring-gray-200/50 opacity-60"
      }`}
    >
      <div className="aspect-[16/9] bg-gradient-to-br from-gray-50 to-gray-100 flex items-center justify-center relative overflow-hidden">
        {layout.preview_blob_url ? (
          <img
            src={layout.preview_blob_url}
            alt={layout.name}
            loading="lazy"
            className="w-full h-full object-contain"
          />
        ) : (
          <div className="text-[11px] text-gray-400 flex items-center gap-1.5">
            <AlertCircle size={12} />
            no preview
          </div>
        )}
        {isDefault && (
          <span className="absolute top-2 left-2 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded-full ring-1 ring-amber-100">
            <Star size={10} fill="currentColor" />
            default
          </span>
        )}
        {repeatCount > 1 && (
          <span
            title={`This shape (name + kind) appears ${repeatCount} times across the master's themes — toggle each variant individually for per-theme control.`}
            className="absolute top-2 right-2 inline-flex items-center gap-1 text-[10px] font-bold tracking-wider text-gray-600 bg-white/90 backdrop-blur px-1.5 py-0.5 rounded-full ring-1 ring-gray-200"
          >
            ×{repeatCount}
          </span>
        )}
      </div>

      <div className="p-3.5 flex flex-col gap-2">
        <div className="min-w-0">
          <h4
            className="text-[13px] font-semibold text-gray-900 truncate"
            title={layout.name}
          >
            {layout.name || "(unnamed)"}
          </h4>
          <p className="text-[10px] text-gray-400 font-mono">
            m{layout.master_index}·l{layout.layout_index}
          </p>
          <PlaceholderAnatomy placeholders={layout.placeholders || []} />
        </div>

        <div className="flex items-center gap-1.5">
          <select
            value={layout.user_kind ?? ""}
            onChange={handleKind}
            disabled={busy}
            className="flex-1 min-w-0 h-7 px-2 text-[11px] rounded-md ring-1 ring-gray-200 bg-white hover:ring-gray-300 focus:ring-brand focus:outline-none disabled:opacity-50 cursor-pointer truncate"
            title={
              overridden
                ? `Auto: ${layout.auto_kind} — overridden`
                : `Auto-classified as ${layout.auto_kind}`
            }
          >
            {KIND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
                {o.value === "" && layout.auto_kind
                  ? ` (${layout.auto_kind})`
                  : ""}
              </option>
            ))}
          </select>

          <button
            onClick={() => onMarkDefault()}
            disabled={busy || isDefault}
            title={isDefault ? "Already the default for this kind" : `Make default for ${kind}`}
            className={`h-7 w-7 rounded-md flex items-center justify-center cursor-pointer transition-colors ${
              isDefault
                ? "text-amber-600 bg-amber-50"
                : "text-gray-300 hover:text-amber-600 hover:bg-amber-50"
            } disabled:cursor-not-allowed`}
          >
            <Star size={13} fill={isDefault ? "currentColor" : "none"} />
          </button>

          <button
            onClick={handleEnable}
            disabled={busy}
            title={enabled ? "Disable (hide from agent menu)" : "Enable"}
            className="h-7 w-7 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors flex items-center justify-center cursor-pointer disabled:opacity-50"
          >
            {enabled ? <Eye size={13} /> : <EyeOff size={13} />}
          </button>
        </div>

        <textarea
          rows={1}
          defaultValue={layout.notes ?? ""}
          onBlur={handleNotesBlur}
          disabled={busy}
          placeholder="Notes for the agent…"
          className="text-[11px] px-2 py-1.5 rounded-md ring-1 ring-gray-200 bg-white hover:ring-gray-300 focus:ring-brand focus:outline-none disabled:opacity-50 resize-none leading-snug"
        />
      </div>
    </li>
  );
}

// Compact anatomy strip: counts placeholders by role and surfaces any
// locked chrome text. Helps the user verify "what is this layout"
// at a glance — the PNG above shows visual structure, this strip
// shows the structured data the renderer will actually consume.
function PlaceholderAnatomy({ placeholders }) {
  if (!placeholders || placeholders.length === 0) return null;
  const counts = placeholders.reduce((acc, p) => {
    const r = p.role || "other";
    acc[r] = (acc[r] || 0) + 1;
    return acc;
  }, {});
  const lockedTexts = placeholders
    .map((p) => p.text)
    .filter((t) => typeof t === "string" && t.trim() !== "");
  // Show roles in a deterministic order so cards align visually.
  const ORDER = [
    "title", "subtitle", "body", "logo",
    "footer", "date", "page_number", "other",
  ];
  const ordered = ORDER.filter((r) => counts[r]).map((r) => [r, counts[r]]);
  const ROLE_ABBREV = {
    title: "T", subtitle: "ST", body: "B", logo: "L",
    footer: "F", date: "D", page_number: "#", other: "?",
  };
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {ordered.map(([role, n]) => (
        <span
          key={role}
          title={`${n} × ${role}`}
          className="text-[9px] font-mono px-1 py-px rounded bg-gray-100 text-gray-600"
        >
          {ROLE_ABBREV[role] || role.slice(0, 1).toUpperCase()}
          {n > 1 ? `×${n}` : ""}
        </span>
      ))}
      {lockedTexts.length > 0 && (
        <span
          title={`Locked text: ${lockedTexts.join(" / ")}`}
          className="text-[9px] font-mono px-1 py-px rounded bg-amber-50 text-amber-700 ring-1 ring-amber-100"
        >
          🔒{lockedTexts.length}
        </span>
      )}
    </div>
  );
}
