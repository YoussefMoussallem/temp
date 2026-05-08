import { useEffect, useMemo, useState } from "react";
import { Save, AlertCircle, Check } from "lucide-react";
import { useAdminApi, useAdminMutation } from "../hooks/useAdminApi";

// Tenant-wide model selection. Four settings:
//   - default_model: main agent loop + cost recording.
//   - search_model:  WebSearch tool (empty = fall back to default).
//   - export_model:  ExportDeck tool + export-deck SSE endpoint
//                    (empty = fall back to default).
//   - title_model:   Conversation auto-title generator
//                    (empty = fall back to default).
//
// The `<empty>` option is rendered as "(use default model)" for the
// search/export/title selectors so admins can opt out without typing
// anything. The default_model selector intentionally has no empty
// option — every deployment must have a main model configured.

const SUCCESS_RESET_MS = 2500;

function groupByProvider(models) {
  const groups = {};
  for (const m of models) {
    const dot = m.id.indexOf(".");
    const provider = dot > 0 ? m.id.slice(0, dot) : "other";
    (groups[provider] ??= []).push(m);
  }
  for (const k of Object.keys(groups)) {
    groups[k].sort((a, b) => a.id.localeCompare(b.id));
  }
  return Object.fromEntries(
    Object.entries(groups).sort(([a], [b]) => a.localeCompare(b)),
  );
}

function ModelSelect({ label, hint, value, onChange, models, allowEmpty }) {
  const groups = useMemo(() => groupByProvider(models), [models]);
  return (
    <div>
      <label className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 block mb-2">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2.5 text-sm bg-gray-50 rounded-xl outline-none cursor-pointer transition-all
                   border border-gray-200/60 hover:border-gray-300 focus:border-brand/30 focus:ring-2 focus:ring-brand/5"
      >
        {allowEmpty && (
          <option value="">(use default model)</option>
        )}
        {Object.entries(groups).map(([provider, ms]) => (
          <optgroup key={provider} label={provider}>
            {ms.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id.slice(provider.length + 1) || m.id}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {hint && (
        <p className="mt-1.5 text-[10px] text-gray-400">{hint}</p>
      )}
    </div>
  );
}

export default function ModelsPage() {
  const settingsApi = useAdminApi("/api/admin/settings/models");
  const modelsApi = useAdminApi("/api/agent/models");
  const { mutate, busy } = useAdminMutation();

  const allModels = Array.isArray(modelsApi.data) ? modelsApi.data : [];

  // Local form state — initialised from the server response, then
  // edited in place. We submit the diff (only changed keys) so a
  // partial update doesn't accidentally clobber another field.
  const [form, setForm] = useState({
    default_model: "",
    search_model: "",
    export_model: "",
    title_model: "",
  });
  const [serverState, setServerState] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [saved, setSaved] = useState(false);

  // Single source of truth for which keys this page manages. Adding a
  // new admin-managed model becomes a one-line change to this list +
  // a new <ModelSelect> row below.
  const MODEL_KEYS = ["default_model", "search_model", "export_model", "title_model"];

  useEffect(() => {
    if (settingsApi.data) {
      const next = Object.fromEntries(
        MODEL_KEYS.map((k) => [k, settingsApi.data[k] ?? ""]),
      );
      setForm(next);
      setServerState(next);
    }
  }, [settingsApi.data]);

  const dirty = serverState && MODEL_KEYS.some(
    (k) => form[k] !== serverState[k],
  );

  const handleSave = async () => {
    if (!dirty || !serverState) return;
    setSaveError(null);
    setSaved(false);
    const diff = {};
    for (const key of MODEL_KEYS) {
      if (form[key] !== serverState[key]) diff[key] = form[key];
    }
    try {
      const updated = await mutate("PUT", "/api/admin/settings/models", diff);
      const next = Object.fromEntries(
        MODEL_KEYS.map((k) => [k, updated?.[k] ?? ""]),
      );
      setForm(next);
      setServerState(next);
      setSaved(true);
      window.setTimeout(() => setSaved(false), SUCCESS_RESET_MS);
    } catch (e) {
      setSaveError(
        e?.message?.replace(/^HTTP \d+:\s*/, "") || "Failed to save settings",
      );
    }
  };

  const loading = settingsApi.loading || modelsApi.loading;
  const loadError = settingsApi.error || modelsApi.error;

  return (
    <div className="max-w-2xl">
      <h2 className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-3">
        Model Defaults
      </h2>

      {loading && (
        <div className="text-[12px] text-gray-400">Loading…</div>
      )}

      {loadError && !loading && (
        <div className="mb-3 text-[12px] text-red-600 bg-red-50 rounded-lg px-3 py-2 flex items-center gap-2">
          <AlertCircle size={12} />
          <span>{loadError}</span>
        </div>
      )}

      {!loading && !loadError && (
        <>
          <p className="text-[12px] text-gray-500 mb-5 leading-relaxed">
            These models are applied to every user in the deployment. Changes
            take effect on the next chat turn (the backend caches values for
            up to 60 seconds).
          </p>

          <div className="bg-white border border-gray-200/60 rounded-2xl p-5 flex flex-col gap-5">
            <ModelSelect
              label="Main Model"
              hint="Used by the agent loop for every chat turn and for cost / usage recording."
              value={form.default_model}
              onChange={(v) => setForm((p) => ({ ...p, default_model: v }))}
              models={allModels}
            />
            <ModelSelect
              label="Search Model"
              hint="Used by the WebSearch tool. Leave on '(use default model)' to reuse the main model."
              value={form.search_model}
              onChange={(v) => setForm((p) => ({ ...p, search_model: v }))}
              models={allModels}
              allowEmpty
            />
            <ModelSelect
              label="Export Model"
              hint="Used by the deck-panel Export button and the agent's ExportDeck tool to convert each slide's HTML to a pptxgenjs spec."
              value={form.export_model}
              onChange={(v) => setForm((p) => ({ ...p, export_model: v }))}
              models={allModels}
              allowEmpty
            />
            <ModelSelect
              label="Title Model"
              hint="Used to auto-generate a 4–6 word title for new conversations from the user's first message. Pick a small/fast model — title generation is short and latency-sensitive."
              value={form.title_model}
              onChange={(v) => setForm((p) => ({ ...p, title_model: v }))}
              models={allModels}
              allowEmpty
            />
          </div>

          {saveError && (
            <div className="mt-3 text-[12px] text-red-600 bg-red-50 rounded-lg px-3 py-2 flex items-center gap-2">
              <AlertCircle size={12} />
              <span>{saveError}</span>
            </div>
          )}

          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              disabled={!dirty || busy}
              onClick={handleSave}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-[12px] font-medium bg-brand text-white hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Save size={12} />
              {busy ? "Saving…" : "Save changes"}
            </button>
            {saved && (
              <span className="inline-flex items-center gap-1.5 text-[11px] text-emerald-700">
                <Check size={12} />
                Saved
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
