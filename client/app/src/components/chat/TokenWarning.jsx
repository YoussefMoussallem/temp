import { AlertTriangle, X } from "lucide-react";

/**
 * Top-of-chat banner shown when the backend's `compact_warning_hook`
 * fires — i.e. context fill is at or above 70% of the autocompact
 * threshold. Wired to the SSE `compact_warning` event in `useChat`.
 *
 * Phase 3.6 scope:
 *   - Banner renders when `warning?.should_show && !dismissed`.
 *   - Dismiss button (×) hides the banner; the parent stores the
 *     fill_pct at dismissal time so a subsequent warning that crosses
 *     a *higher* fill level un-dismisses (re-arm pattern matches
 *     source's "re-shown on next threshold cross" requirement).
 *   - Optional "Compact now" button POSTs `/compact` via the same
 *     send() path as a typed slash command. Hidden when `onCompactNow`
 *     is not provided.
 *
 * Props:
 *   - `warning`       — the `WarningState` payload from SSE, or null
 *                       when no warning has fired this session.
 *   - `dismissed`     — boolean: true means the user clicked × at the
 *                       current fill_pct.
 *   - `onDismiss()`   — called when × clicked.
 *   - `onCompactNow()`— optional; called when "Compact now" clicked.
 *                       When omitted, the button is hidden.
 *   - `disabled`      — pass true while the chat is busy / the input
 *                       is disabled (viewer mode, no conversation, etc.).
 *                       Disables the "Compact now" button.
 */
export default function TokenWarning({
  warning,
  dismissed = false,
  onDismiss,
  onCompactNow,
  disabled = false,
}) {
  if (!warning?.should_show || dismissed) return null;

  const pct = Math.min(100, Math.round((warning.fill_pct ?? 0) * 100));
  const current = warning.current_tokens ?? 0;

  return (
    <div className="px-3 py-2 border-b border-amber-200 bg-amber-50/60 flex items-center gap-2 text-[11px] text-amber-800">
      <AlertTriangle size={12} className="shrink-0 text-amber-600" />

      <span className="flex-1 leading-tight">
        Context is <strong>{pct}%</strong> full ({current.toLocaleString()} tokens).{" "}
        {onCompactNow ? "Run /compact" : "Compaction"} will summarise older messages.
      </span>

      {onCompactNow && (
        <button
          type="button"
          onClick={onCompactNow}
          disabled={disabled}
          className="px-2 py-0.5 rounded border border-amber-300 bg-white text-amber-800 hover:bg-amber-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-[10px] font-medium"
        >
          Compact now
        </button>
      )}

      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss warning"
        className="ml-1 p-0.5 rounded hover:bg-amber-100 transition-colors"
      >
        <X size={12} />
      </button>
    </div>
  );
}
