import { useState } from "react";
import { Save, X } from "lucide-react";

const USER_TYPES = ["user", "feedback", "reference"];
const PROJECT_TYPES = ["project", "decision", "stakeholder", "reference"];

const TYPE_COPY = {
  user: "User — identity / role / preferences",
  feedback: "Feedback — correction or validated approach",
  reference: "Reference — pointer to an external resource",
  project: "Project — general fact about this deck",
  decision: "Decision — explicit choice made for this deck",
  stakeholder: "Stakeholder — audience or reviewer info",
};

const SLUG_PATTERN = /^[a-z0-9_]+$/;

/**
 * Create / edit form for one memory entry.
 *
 * Pass ``existing`` to edit (slug becomes read-only since it's the
 * stable handle and DB upserts on slug — changing it would orphan
 * the original row). Omit ``existing`` for create.
 *
 * Mirrors the validation rules baked into the agent tools (slug
 * regex, 150-char description cap, scope-appropriate types) so a
 * memory written here can't fail the server-side check.
 */
export default function MemoryEditor({ scope, existing, onSave, onCancel }) {
  const isEdit = !!existing;
  const [slug, setSlug] = useState(existing?.slug ?? "");
  const [type, setType] = useState(
    existing?.type ?? (scope === "user" ? "feedback" : "project"),
  );
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [body, setBody] = useState(existing?.body ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const types = scope === "user" ? USER_TYPES : PROJECT_TYPES;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!slug || !SLUG_PATTERN.test(slug)) {
      setError("Slug must be lowercase letters, digits, and underscores only.");
      return;
    }
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    if (!description.trim()) {
      setError("Description is required.");
      return;
    }
    if (description.length > 150) {
      setError("Description must be ≤ 150 characters.");
      return;
    }
    if (!body.trim()) {
      setError("Body is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave({
        slug: slug.trim(),
        type,
        name: name.trim(),
        description: description.trim(),
        body,
      });
    } catch (e) {
      setError(e?.message ?? "Save failed.");
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-xl border border-gray-200 bg-white p-4 flex flex-col gap-3"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-gray-800">
          {isEdit ? `Edit [${scope}:${existing.slug}]` : `New ${scope} memory`}
        </h3>
        <button
          type="button"
          onClick={onCancel}
          className="w-6 h-6 rounded-md hover:bg-gray-100 flex items-center justify-center transition-colors cursor-pointer"
        >
          <X size={14} className="text-gray-400" />
        </button>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">
          Slug
        </label>
        <input
          type="text"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          disabled={isEdit}
          placeholder="e.g. feedback_no_emoji"
          className={`text-[12px] border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand ${
            isEdit ? "bg-gray-50 text-gray-500 cursor-not-allowed" : ""
          }`}
        />
        {!isEdit && (
          <span className="text-[10px] text-gray-400">
            Lowercase letters, digits, underscores. Re-using an existing slug overwrites.
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">
          Type
        </label>
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="text-[12px] border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand"
        >
          {types.map((t) => (
            <option key={t} value={t}>
              {TYPE_COPY[t] ?? t}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">
          Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
          placeholder="Human-readable title"
          className="text-[12px] border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand"
        />
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between">
          <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">
            Description
          </label>
          <span
            className={`text-[10px] ${
              description.length > 150 ? "text-red-600" : "text-gray-400"
            }`}
          >
            {description.length}/150
          </span>
        </div>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={150}
          placeholder="One-line hook the agent sees in the index"
          className="text-[12px] border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wide">
          Body
        </label>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={6}
          placeholder="Full content as markdown. Include **Why** and **How to apply** for feedback / decisions."
          className="text-[12px] font-mono border border-gray-200 rounded-lg px-3 py-2 resize-y min-h-[100px] focus:outline-none focus:ring-1 focus:ring-brand/40 focus:border-brand"
        />
      </div>

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
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="text-[12px] font-medium px-3 py-1.5 rounded-lg bg-brand text-white hover:bg-brand/90 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
        >
          <Save size={12} />
          {saving ? "Saving…" : isEdit ? "Save changes" : "Create"}
        </button>
      </div>
    </form>
  );
}
