import { useState } from "react";
import { Sparkles, Loader2, X } from "lucide-react";

/**
 * Natural-language memory composer — used for both create AND edit.
 *
 * Create: pass no ``initialText`` and an ``onSubmit(text)`` that
 * routes to a fresh save. The LLM picks the slug.
 *
 * Edit: pass ``initialText`` (the existing body) and an
 * ``onSubmit(text)`` that routes to a slug-preserving save. The
 * backend forces the slug so the upsert overwrites in place.
 *
 * The user never sees slug / type / name / description / body
 * separately — they write plain text, the AI structures.
 */
export default function MemoryComposer({
  scope,
  initialText = "",
  onSubmit,
  onCancel,
  mode = "create",
}) {
  const [text, setText] = useState(initialText);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const isUser = scope === "user";
  const isEdit = mode === "edit";

  const titleCopy = isEdit
    ? isUser
      ? "Update what I remember about you"
      : "Update what I remember about this project"
    : isUser
      ? "What should I remember about you?"
      : "What should I remember about this project?";

  const placeholder = isUser
    ? "e.g. I prefer terse summaries after tool calls.\ne.g. Don't use emoji in slides.\ne.g. I default to Strategy& brand for consulting decks."
    : "e.g. The audience is a PE investment committee — 5 senior partners.\ne.g. Pitch deadline is March 15.\ne.g. Headline takeaway: investment is feasible despite tier-2 market risks.";

  const helpCopy = isEdit
    ? "Edit in plain English. I'll restructure the saved version to match — keeping the same entry, not creating a new one."
    : isUser
      ? "Write in plain English. I'll keep this across every conversation you have."
      : "Write in plain English. I'll only remember this when we're working on this deck.";

  const submitLabel = isEdit ? "Update" : "Save";

  const handleSubmit = async (e) => {
    e.preventDefault();
    const value = text.trim();
    if (!value) return;
    setSaving(true);
    setError(null);
    try {
      await onSubmit(value);
      // Reset on create so the composer can be reused. Edit closes
      // out via the parent.
      if (!isEdit) setText("");
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
        <h3 className="text-[12px] font-semibold text-gray-800 flex-1">
          {titleCopy}
        </h3>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="w-6 h-6 rounded-md hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer disabled:opacity-50"
            aria-label="Cancel"
          >
            <X size={14} className="text-gray-400" />
          </button>
        )}
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        rows={8}
        autoFocus
        className="text-[13px] border border-gray-200 rounded-lg px-3 py-3 resize-y min-h-[180px] focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand leading-relaxed"
      />

      <p className="text-[10px] text-gray-400 leading-relaxed">{helpCopy}</p>

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
              {isEdit ? "Updating…" : "Saving…"}
            </>
          ) : (
            <>
              <Sparkles size={12} />
              {submitLabel}
            </>
          )}
        </button>
      </div>
    </form>
  );
}
