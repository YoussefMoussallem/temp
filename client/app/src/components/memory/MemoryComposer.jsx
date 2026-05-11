import { useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";

/**
 * Natural-language memory composer.
 *
 * One textarea. The user writes what they want the agent to remember.
 * On submit the backend LLM structures it into slug / type / name /
 * description / body and saves. The user never sees those fields —
 * the resulting card shows a friendly summary and lets them tweak
 * directly via inline edit.
 *
 * Placeholder copy + framing differs by scope so the user has a clear
 * mental model of what gets remembered where.
 */
export default function MemoryComposer({ scope, onCreate, onCancel }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const isUser = scope === "user";

  const placeholder = isUser
    ? "e.g. I prefer terse summaries after tool calls.\ne.g. Don't use emoji in slides.\ne.g. I default to Strategy& brand for consulting decks."
    : "e.g. The audience is a PE investment committee — 5 senior partners.\ne.g. Pitch deadline is March 15.\ne.g. Headline takeaway: investment is feasible despite tier-2 market risks.";

  const handleSubmit = async (e) => {
    e.preventDefault();
    const value = text.trim();
    if (!value) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate(value);
      setText("");
    } catch (err) {
      setError(err?.message ?? "Couldn't save. Try again?");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-xl border border-gray-200 bg-white p-4 flex flex-col gap-3 shadow-sm"
    >
      <div className="flex items-center gap-2">
        <Sparkles size={14} className="text-brand" />
        <h3 className="text-[12px] font-semibold text-gray-800">
          {isUser
            ? "What should I remember about you?"
            : "What should I remember about this project?"}
        </h3>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        rows={8}
        autoFocus
        className="text-[13px] border border-gray-200 rounded-lg px-3 py-3 resize-y min-h-[180px] focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand leading-relaxed"
      />

      <p className="text-[10px] text-gray-400 leading-relaxed">
        {isUser
          ? "Write in plain English. I'll keep this across every conversation you have."
          : "Write in plain English. I'll only remember this when we're working on this deck."}
      </p>

      {error && (
        <div className="text-[11px] text-red-600 bg-red-50 border border-red-100 rounded-md px-2.5 py-1.5">
          {error}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="text-[12px] font-medium px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors cursor-pointer"
          disabled={saving}
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving || !text.trim()}
          className="text-[12px] font-medium px-3 py-1.5 rounded-lg bg-brand text-white hover:bg-brand/90 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
        >
          {saving ? (
            <>
              <Loader2 size={12} className="animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <Sparkles size={12} />
              Save
            </>
          )}
        </button>
      </div>
    </form>
  );
}
