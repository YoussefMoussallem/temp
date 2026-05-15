// Master Manager — full-screen surface for a project's templates.
//
// One card per imported master. The card shows what the extractor
// pulled out so the user has a fighting chance of spotting an
// extraction problem (wrong colors, missing chrome) before it
// pollutes generation.
//
// Pattern matches MemoryPage / ProjectsPage: receives ``onBack`` from
// the parent App and stays inside the existing nav surface (no
// react-router top-level routing).

import { useRef, useState } from "react";
import {
  Upload,
  Loader2,
  Check,
  Trash2,
  AlertCircle,
  ArrowLeft,
  Star,
  Type,
  X,
} from "lucide-react";
import { computeMissingBrandFonts } from "../utils/brandFonts.js";
import { useMasters } from "../hooks/useMasters.js";
import Header from "../components/common/Header.jsx";

const _FONT_ACCEPT = ".ttf,.otf,.woff,.woff2";
const _FONT_EXTS = new Set(["ttf", "otf", "woff", "woff2"]);

function _isFontFile(file) {
  const name = file?.name || "";
  const ext = name.includes(".")
    ? name.slice(name.lastIndexOf(".") + 1).toLowerCase()
    : "";
  return _FONT_EXTS.has(ext);
}

export default function MastersPage({
  projectId,
  projectName,
  onBack,
  onOpenMaster,
  getToken,
  onOpenUserMemory,
}) {
  const masters = useMasters(projectId, getToken);
  const fileInputRef = useRef(null);
  const fontInputRef = useRef(null);
  const [busy, setBusy] = useState(null); // null | "uploading" | "deleting" | "activating"
  const [pageError, setPageError] = useState(null);
  // Staged before submit so the user can attach fonts after picking the
  // .pptx without committing to upload yet. Cleared on success / cancel.
  const [stagedPptx, setStagedPptx] = useState(null);
  const [stagedFonts, setStagedFonts] = useState([]);

  const onPickFile = () => fileInputRef.current?.click();
  const onPickFonts = () => fontInputRef.current?.click();

  const onFile = (e) => {
    const file = e.target.files?.[0];
    if (e.target) e.target.value = "";
    if (!file) return;
    setStagedPptx(file);
    setPageError(null);
  };

  const onFonts = (e) => {
    const picked = Array.from(e.target.files || []);
    if (e.target) e.target.value = "";
    const valid = picked.filter(_isFontFile);
    const skipped = picked.length - valid.length;
    if (skipped > 0) {
      setPageError(
        `Skipped ${skipped} file${skipped === 1 ? "" : "s"} — only .ttf / .otf / .woff / .woff2 are allowed.`,
      );
    }
    if (!valid.length) return;
    // Dedup by name so re-picking the same family doesn't double up.
    setStagedFonts((prev) => {
      const seen = new Set(prev.map((f) => f.name));
      return [...prev, ...valid.filter((f) => !seen.has(f.name))];
    });
  };

  const removeStagedFont = (name) => {
    setStagedFonts((prev) => prev.filter((f) => f.name !== name));
  };

  const cancelStaging = () => {
    setStagedPptx(null);
    setStagedFonts([]);
    setPageError(null);
  };

  const onSubmit = async () => {
    if (!stagedPptx) return;
    setBusy("uploading");
    setPageError(null);
    try {
      await masters.upload(stagedPptx, stagedFonts);
      setStagedPptx(null);
      setStagedFonts([]);
    } catch (err) {
      setPageError(err?.message || "Upload failed");
    } finally {
      setBusy(null);
    }
  };

  const onActivate = async (id) => {
    setBusy("activating");
    setPageError(null);
    try {
      await masters.activate(id);
    } catch (err) {
      setPageError(err?.message || "Activate failed");
    } finally {
      setBusy(null);
    }
  };

  const onDelete = async (id) => {
    if (!window.confirm("Delete this master? This cannot be undone.")) return;
    setBusy("deleting");
    setPageError(null);
    try {
      await masters.remove(id);
    } catch (err) {
      setPageError(err?.message || "Delete failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gradient-to-b from-gray-50 to-gray-100">
      <Header
        activeProjectName={projectName}
        onBackToProjects={onBack}
        onOpenUserMemory={onOpenUserMemory}
        showDeckActions={false}
      />

      <div className="flex-1 overflow-y-auto px-8 py-6">
        <div className="max-w-5xl mx-auto">
          <div className="flex items-center gap-2 mb-2">
            <button
              onClick={onBack}
              className="text-[12px] text-gray-500 hover:text-gray-700 flex items-center gap-1"
            >
              <ArrowLeft size={12} />
              Back to chat
            </button>
          </div>
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-gray-900 font-[var(--font-heading)]">
                Master templates
              </h1>
              <p className="text-sm text-gray-500 mt-1 max-w-2xl leading-relaxed">
                Imported PowerPoint templates. The active master sets the
                canvas, theme, layouts, and locked chrome for every slide
                generated in this project.
              </p>
            </div>
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pptx,.potx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
                onChange={onFile}
                className="hidden"
              />
              <input
                ref={fontInputRef}
                type="file"
                accept={_FONT_ACCEPT}
                multiple
                onChange={onFonts}
                className="hidden"
              />
              <button
                onClick={onPickFile}
                disabled={busy === "uploading" || stagedPptx !== null}
                className="h-9 px-3.5 rounded-lg flex items-center gap-2 text-[12px] font-medium
                           text-brand bg-brand-dim hover:bg-brand/10 transition-colors cursor-pointer
                           disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {busy === "uploading" ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Upload size={14} />
                )}
                <span>
                  {busy === "uploading"
                    ? "Importing…"
                    : stagedPptx
                      ? "Master selected"
                      : "Import master"}
                </span>
              </button>
            </div>
          </div>

          {stagedPptx && (
            <StagingPanel
              pptx={stagedPptx}
              fonts={stagedFonts}
              busy={busy === "uploading"}
              onPickFonts={onPickFonts}
              onRemoveFont={removeStagedFont}
              onSubmit={onSubmit}
              onCancel={cancelStaging}
            />
          )}

          {pageError && (
            <div className="mb-4 px-4 py-3 rounded-lg bg-red-50 ring-1 ring-red-200 text-[12px] text-red-700 flex items-start gap-2">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{pageError}</span>
            </div>
          )}

          {masters.loading && masters.masters.length === 0 ? (
            <div className="text-center py-16 text-gray-400 text-sm">
              Loading…
            </div>
          ) : masters.masters.length === 0 ? (
            <EmptyState />
          ) : (
            <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {masters.masters.map((m) => (
                <MasterCard
                  key={m.id}
                  master={m}
                  isActive={masters.activeMasterId === m.id}
                  onOpen={() => onOpenMaster?.(m.id)}
                  onActivate={() => onActivate(m.id)}
                  onDelete={() => onDelete(m.id)}
                  busy={busy}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function StagingPanel({
  pptx,
  fonts,
  busy,
  onPickFonts,
  onRemoveFont,
  onSubmit,
  onCancel,
}) {
  const fontTotalKb = Math.round(
    fonts.reduce((sum, f) => sum + (f.size || 0), 0) / 1024,
  );

  return (
    <div className="mb-4 p-4 rounded-xl bg-white ring-1 ring-gray-200 shadow-sm">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="min-w-0 flex items-center gap-2 text-[12px]">
          <Upload size={14} className="text-brand shrink-0" />
          <span className="font-medium text-gray-800 truncate">{pptx.name}</span>
          <span className="text-gray-400 font-mono shrink-0">
            {Math.round(pptx.size / 1024)} KB
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onPickFonts}
            disabled={busy}
            className="h-8 px-3 rounded-md flex items-center gap-1.5 text-[11px] font-medium
                       text-gray-700 bg-gray-100 hover:bg-gray-200 transition-colors cursor-pointer
                       disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <Type size={12} />
            <span>Add brand fonts</span>
          </button>
          <button
            onClick={onSubmit}
            disabled={busy}
            className="h-8 px-3 rounded-md flex items-center gap-1.5 text-[11px] font-medium
                       text-white bg-brand hover:opacity-90 transition-opacity cursor-pointer
                       disabled:opacity-60 disabled:cursor-wait"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            <span>{busy ? "Uploading…" : "Upload"}</span>
          </button>
          <button
            onClick={onCancel}
            disabled={busy}
            title="Cancel"
            className="h-8 w-8 rounded-md flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {fonts.length > 0 ? (
        <div className="pt-2 border-t border-gray-100">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-gray-400">
              Bundled fonts
            </span>
            <span className="text-[10px] text-gray-400 font-mono">
              {fonts.length} file{fonts.length === 1 ? "" : "s"} · {fontTotalKb} KB
            </span>
          </div>
          <ul className="flex flex-wrap gap-1.5">
            {fonts.map((f) => (
              <li
                key={f.name}
                className="flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-md bg-gray-50 text-[11px] text-gray-700"
              >
                <span className="font-mono">{f.name}</span>
                <button
                  onClick={() => onRemoveFont(f.name)}
                  disabled={busy}
                  title="Remove"
                  className="w-4 h-4 rounded flex items-center justify-center text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <X size={10} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-[11px] text-gray-400 leading-relaxed pt-1 border-t border-gray-100">
          Optional — attach .ttf / .otf / .woff / .woff2 files so the brand fonts render correctly. Family + weight are inferred from each filename.
        </p>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-20 px-6">
      <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-white shadow-sm mb-5">
        <Upload size={22} className="text-gray-300" />
      </div>
      <h2 className="text-lg font-semibold text-gray-800 mb-1.5 font-[var(--font-heading)]">
        No masters yet
      </h2>
      <p className="text-sm text-gray-500 max-w-md mx-auto leading-relaxed">
        Click <span className="font-medium text-gray-700">Import master</span>{" "}
        in the header to upload a PowerPoint template (.pptx). Subsequent
        slides will inherit its brand, layouts, and chrome.
      </p>
    </div>
  );
}

function MasterCard({ master, isActive, onOpen, onActivate, onDelete, busy }) {
  const m = master.manifest || {};
  const theme = m.theme || {};
  const fallbackColors = theme.colors || {};
  const canvas = m.canvas || {};
  // Phase 2.1+: layouts live under masters[].layouts. Sum across them
  // when present so the count reflects what curation will show. Falls
  // back to the legacy top-level ``layouts[]`` for pre-2.1 rows.
  const layoutCount = Array.isArray(m.masters) && m.masters.length > 0
    ? m.masters.reduce(
        (sum, me) => sum + (Array.isArray(me.layouts) ? me.layouts.length : 0),
        0,
      )
    : (Array.isArray(m.layouts) ? m.layouts.length : 0);
  // Layout-name preview list: dedup by name (multi-master decks repeat
  // ``Title Slide`` etc. across themes) so we don't show the same name
  // 11 times.
  const allLayouts = Array.isArray(m.masters) && m.masters.length > 0
    ? m.masters.flatMap((me) => me.layouts || [])
    : (Array.isArray(m.layouts) ? m.layouts : []);
  const dedupedLayouts = (() => {
    const seen = new Set();
    const out = [];
    for (const l of allLayouts) {
      const key = `${l.name}|${l.kind}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(l);
    }
    return out;
  })();
  // Phase C: bundled brand fonts. Empty array on rows uploaded before
  // the feature shipped, or when the user didn't attach any.
  const fontsAssets = Array.isArray(master.fonts_assets) ? master.fonts_assets : [];

  // Surface ALL extracted typography on the card so the user can spot
  // their brand at a glance — masters[0] is often a generic Office
  // theme; the brand-coloured master might be #5+. Single-theme decks
  // collapse cleanly to one row.
  const fontsReferenced =
    Array.isArray(m.fonts_referenced) && m.fonts_referenced.length > 0
      ? m.fonts_referenced
      : [theme.fonts?.major, theme.fonts?.minor].filter(Boolean);

  // Brand fonts the manifest references but the user hasn't bundled —
  // surfaced as a small alert so it's actionable from the list view.
  const missingBrandFonts = computeMissingBrandFonts(fontsReferenced, fontsAssets);

  const themes =
    Array.isArray(m.themes) && m.themes.length > 0
      ? m.themes
      : [{ palette: fallbackColors }];

  // Pick the most "branded" theme — non-grayscale primary wins over a
  // black/white/gray default. Falls back to themes[0] when nothing is
  // distinctive (e.g. a true monochrome template).
  const isGray = (hex) => {
    if (!hex || !/^#[0-9a-fA-F]{6}$/.test(hex)) return true;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return Math.max(r, g, b) - Math.min(r, g, b) < 16;
  };
  const orderedThemes = [...themes].sort((a, b) => {
    const ag = isGray(a.palette?.primary);
    const bg = isGray(b.palette?.primary);
    if (ag === bg) return 0;
    return ag ? 1 : -1;
  });

  const renderSwatches = (colors) =>
    ["primary", "secondary", "text", "bg"].map((key) => (
      <div
        key={key}
        title={`${key}: ${colors[key] || "?"}`}
        className="w-5 h-5 rounded-full ring-1 ring-black/5"
        style={{
          background:
            typeof colors[key] === "string" ? colors[key] : "#ffffff",
        }}
      />
    ));

  return (
    <li className="bg-white rounded-2xl ring-1 ring-gray-200/80 shadow-sm p-5 flex flex-col gap-3 hover:ring-gray-300 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <h3 className="text-[14px] font-semibold text-gray-900 truncate">
              {master.name}
            </h3>
            {isActive && (
              <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded-full">
                <Star size={10} fill="currentColor" />
                active
              </span>
            )}
          </div>
          <p className="text-[11px] text-gray-400 truncate font-mono">
            {master.id}
          </p>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {onOpen && (
            <button
              onClick={onOpen}
              title="Open curation page"
              className="h-7 px-2 rounded-md text-[11px] font-medium text-brand bg-brand-dim hover:bg-brand/10 transition-colors cursor-pointer"
            >
              Curate
            </button>
          )}
          <button
            onClick={onActivate}
            disabled={isActive || busy === "activating"}
            title={isActive ? "Already active" : "Make this the active master"}
            className="h-7 px-2 rounded-md text-[11px] font-medium
                       text-emerald-700 bg-emerald-50 hover:bg-emerald-100
                       disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer
                       flex items-center gap-1"
          >
            <Check size={11} />
            {isActive ? "Active" : "Activate"}
          </button>
          <button
            onClick={onDelete}
            disabled={busy === "deleting"}
            title="Delete master"
            className="h-7 w-7 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors flex items-center justify-center cursor-pointer"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 text-[11px]">
        <div>
          <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1">
            Canvas
          </div>
          <div className="font-mono text-gray-700">
            {canvas.w || "?"}×{canvas.h || "?"}
          </div>
        </div>
        <div>
          <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1">
            Layouts
          </div>
          <div className="text-gray-700">{layoutCount}</div>
        </div>
        <div>
          <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1">
            Fonts referenced
          </div>
          <div
            className="text-gray-700 leading-tight"
            title={fontsReferenced.join(", ")}
          >
            {fontsReferenced.length > 0 ? fontsReferenced.join(", ") : "?"}
          </div>
        </div>
        <div>
          <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1">
            Palettes ({orderedThemes.length})
          </div>
          <div className="flex flex-col gap-1">
            {orderedThemes.map((t, i) => (
              <div
                key={i}
                className="flex items-center gap-1"
                title={`Theme ${t.indices?.[0] ?? i}`}
              >
                {renderSwatches(t.palette || {})}
              </div>
            ))}
          </div>
        </div>
      </div>

      {missingBrandFonts.length > 0 && (
        <div
          className="pt-1 border-t border-gray-100 flex items-start gap-1.5 text-[10px] text-amber-700"
          title={`Re-upload this master with the missing .ttf / .otf files: ${missingBrandFonts.join(", ")}.`}
        >
          <AlertCircle size={11} className="shrink-0 mt-0.5" />
          <span className="leading-tight">
            <span className="font-medium">
              {missingBrandFonts.length} brand font
              {missingBrandFonts.length === 1 ? "" : "s"} not bundled:
            </span>{" "}
            <span className="text-amber-900">
              {missingBrandFonts.slice(0, 3).join(", ")}
              {missingBrandFonts.length > 3 ? `, +${missingBrandFonts.length - 3}` : ""}
            </span>
          </span>
        </div>
      )}

      {fontsAssets.length > 0 && (
        <div className="pt-1 border-t border-gray-100">
          <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1.5 flex items-center gap-1">
            <span>Bundled fonts</span>
            <span className="text-gray-300 font-mono normal-case tracking-normal">
              ({fontsAssets.length})
            </span>
          </div>
          <ul className="flex flex-wrap gap-1">
            {fontsAssets.slice(0, 6).map((f, i) => (
              <li
                key={i}
                title={`${f.family} · weight ${f.weight} · ${f.style}`}
                className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 ring-1 ring-amber-100 font-medium"
              >
                {f.family}{" "}
                <span className="font-mono text-amber-600">{f.weight}</span>
                {f.style === "italic" && (
                  <span className="italic text-amber-600">i</span>
                )}
              </li>
            ))}
            {fontsAssets.length > 6 && (
              <li className="text-[10px] text-gray-400 italic px-1">
                +{fontsAssets.length - 6}
              </li>
            )}
          </ul>
        </div>
      )}

      {dedupedLayouts.length > 0 && (
        <div className="pt-1 border-t border-gray-100">
          <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1.5">
            Layout menu
          </div>
          <ul className="text-[11px] text-gray-600 leading-relaxed">
            {dedupedLayouts.slice(0, 6).map((l, i) => (
              <li key={i} className="truncate">
                <span className="font-mono">{l.name}</span>{" "}
                <span className="text-gray-400">({l.kind})</span>
              </li>
            ))}
            {dedupedLayouts.length > 6 && (
              <li className="text-gray-400 italic">
                +{dedupedLayouts.length - 6} more
              </li>
            )}
          </ul>
        </div>
      )}
    </li>
  );
}
