// Master Manager — detail / curation page.
//
// Reached by clicking a card on MastersPage. Lists every layout in
// the master with PNG previews and per-row controls (kind, enabled,
// default, notes). Activating + deleting a master live here too —
// the list page becomes a thin overview.
//
// The grid filters by master_index when the master has more than 3
// — stc has 11 masters, so a flat 22-card grid is hard to navigate.
// Templates with 1-3 masters render as a single grid (Strategy&'s
// 45 cards is fine because they're all on master 0).

import { useMemo, useState } from "react";
import {
  ArrowLeft,
  Check,
  Trash2,
  AlertCircle,
  Loader2,
  Star,
} from "lucide-react";
import { useMaster } from "../hooks/useMaster.js";
import Header from "../components/common/Header.jsx";
import LayoutCard from "../components/masters/LayoutCard.jsx";
import { computeMissingBrandFonts } from "../utils/brandFonts.js";

export default function MasterDetailPage({
  masterId,
  projectName,
  onBack,
  onDeleted,
  onActivated,
  getToken,
  onOpenUserMemory,
}) {
  const m = useMaster(masterId, getToken);
  const [pageError, setPageError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [pageBusy, setPageBusy] = useState(null); // null | "activating" | "deleting"
  const [masterFilter, setMasterFilter] = useState("all");

  const masterIndices = useMemo(() => {
    const ids = new Set(m.layouts.map((l) => l.master_index));
    return Array.from(ids).sort((a, b) => a - b);
  }, [m.layouts]);

  const visibleLayouts = useMemo(() => {
    if (masterFilter === "all") return m.layouts;
    const idx = parseInt(masterFilter, 10);
    return m.layouts.filter((l) => l.master_index === idx);
  }, [m.layouts, masterFilter]);

  const onPatch = async (layoutId, patch) => {
    setBusyId(layoutId);
    setPageError(null);
    try {
      await m.patchLayout(layoutId, patch);
    } catch (err) {
      setPageError(err?.message || "Update failed");
    } finally {
      setBusyId(null);
    }
  };

  const onMarkDefault = async (layoutId) => {
    setBusyId(layoutId);
    setPageError(null);
    try {
      await m.markDefault(layoutId);
    } catch (err) {
      setPageError(err?.message || "Mark default failed");
    } finally {
      setBusyId(null);
    }
  };

  const onActivate = async () => {
    setPageBusy("activating");
    setPageError(null);
    try {
      await m.activate();
      onActivated?.();
    } catch (err) {
      setPageError(err?.message || "Activate failed");
    } finally {
      setPageBusy(null);
    }
  };

  const onDelete = async () => {
    if (!window.confirm("Delete this master? This cannot be undone."))
      return;
    setPageBusy("deleting");
    setPageError(null);
    try {
      await m.remove();
      onDeleted?.();
    } catch (err) {
      setPageError(err?.message || "Delete failed");
      setPageBusy(null);
    }
  };

  const master = m.master || {};
  const isActive = m.isActive;
  const manifest = master.manifest || {};
  // Phase 2.1+ surfaces multi-master/multi-theme details. Prefer those
  // over the legacy single-master fallback (which only sees masters[0]).
  const themes = manifest.themes || [];
  const fontsReferenced = manifest.fonts_referenced || [];
  // Phase C: bundled brand fonts the user uploaded with the .pptx.
  // Empty for older rows or templates uploaded without fonts.
  const fontsAssets = Array.isArray(master.fonts_assets) ? master.fonts_assets : [];
  // System fonts that don't need bundling are filtered out by
  // ``computeMissingBrandFonts`` — anything left is a brand font the
  // user should upload. Logic lives in ``utils/brandFonts.js`` so the
  // list card can reuse it.
  const missingBrandFonts = computeMissingBrandFonts(fontsReferenced, fontsAssets);
  // Legacy fallback for templates extracted before Phase 2.1.
  const fallbackFonts = (manifest.theme || {}).fonts || {};
  const fallbackColors = (manifest.theme || {}).colors || {};
  const layoutCount = m.layouts.length;
  const enabledCount = m.layouts.filter((l) => l.enabled !== false).length;

  // Multi-master decks (stc has 11) reuse the same layout *shape*
  // across themes. (name, auto_kind) is a cheap proxy for "same shape"
  // — good enough to give curators a sense of how much duplication
  // exists without doing full geometry-signature matching. Pure-name
  // matches are the strong signal; stc has 7 layouts called
  // "12_Content slide _ VCS_to use" and they're conceptually one shape
  // × 7 theme variants.
  const shapeKeys = new Set(
    m.layouts.map((l) => `${l.name}${l.auto_kind}`),
  );
  const distinctShapeCount = shapeKeys.size;
  const shapeRepeatCounts = m.layouts.reduce((acc, l) => {
    const key = `${l.name}${l.auto_kind}`;
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  // Order themes so the most "branded" (non-grayscale primary) comes
  // first — keeps the brand palette as the headline even when masters[0]
  // ships a generic Office default.
  const isGray = (hex) => {
    if (!hex || !/^#[0-9a-fA-F]{6}$/.test(hex)) return true;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return Math.max(r, g, b) - Math.min(r, g, b) < 16;
  };
  const orderedThemes = [...themes].sort((a, b) => {
    const ag = isGray(a?.palette?.primary);
    const bg = isGray(b?.palette?.primary);
    if (ag === bg) return 0;
    return ag ? 1 : -1;
  });

  return (
    <div className="flex flex-col h-screen bg-gradient-to-b from-gray-50 to-gray-100">
      <Header
        activeProjectName={projectName}
        onBackToProjects={onBack}
        onOpenUserMemory={onOpenUserMemory}
        showDeckActions={false}
      />

      <div className="flex-1 overflow-y-auto px-8 py-6">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center gap-2 mb-2">
            <button
              onClick={onBack}
              className="text-[12px] text-gray-500 hover:text-gray-700 flex items-center gap-1"
            >
              <ArrowLeft size={12} />
              Back to masters
            </button>
          </div>

          <div className="flex items-start justify-between mb-6 gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h1 className="text-2xl font-bold tracking-tight text-gray-900 font-[var(--font-heading)] truncate">
                  {master.name || "Master"}
                </h1>
                {isActive && (
                  <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded-full">
                    <Star size={10} fill="currentColor" />
                    active
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-500 max-w-3xl leading-relaxed">
                Curate the layout menu the agent sees. Toggle layouts off
                to remove them from generation; star one per kind as the
                preferred default; rename the auto-detected kind when the
                classifier got it wrong.
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={onActivate}
                disabled={isActive || pageBusy !== null}
                title={isActive ? "Already active" : "Make this the active master"}
                className="h-9 px-3.5 rounded-lg flex items-center gap-2 text-[12px] font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                {pageBusy === "activating" ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Check size={14} />
                )}
                {isActive ? "Active" : "Activate"}
              </button>
              <button
                onClick={onDelete}
                disabled={pageBusy !== null}
                title="Delete master"
                className="h-9 px-3.5 rounded-lg flex items-center gap-2 text-[12px] font-medium text-red-700 bg-red-50 hover:bg-red-100 disabled:opacity-50 transition-colors cursor-pointer"
              >
                {pageBusy === "deleting" ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Trash2 size={14} />
                )}
                Delete
              </button>
            </div>
          </div>

          {pageError && (
            <div className="mb-4 px-4 py-3 rounded-lg bg-red-50 ring-1 ring-red-200 text-[12px] text-red-700 flex items-start gap-2">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{pageError}</span>
            </div>
          )}

          <div className="bg-white rounded-2xl ring-1 ring-gray-200/80 shadow-sm p-5 mb-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-[11px]">
              <Stat label="Layouts" value={`${enabledCount} / ${layoutCount} enabled`} />
              <Stat
                label="Masters"
                value={String(masterIndices.length || 1)}
                hint={
                  distinctShapeCount < layoutCount
                    ? `${distinctShapeCount} distinct shapes`
                    : null
                }
              />
              <div>
                <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1">
                  Fonts referenced
                </div>
                <div className="text-gray-700 leading-tight" title={fontsReferenced.join(", ")}>
                  {fontsReferenced.length > 0
                    ? fontsReferenced.join(", ")
                    : `${fallbackFonts.major || "?"} / ${fallbackFonts.minor || "?"}`}
                </div>
              </div>
              <div>
                <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1">
                  Palettes ({themes.length || 1})
                </div>
                <div className="flex flex-col gap-1.5">
                  {orderedThemes.length > 0 ? (
                    orderedThemes.map((t, i) => (
                      <PaletteSwatches
                        key={i}
                        palette={t.palette || {}}
                        title={`Theme ${t.indices?.[0] ?? i}`}
                      />
                    ))
                  ) : (
                    <PaletteSwatches palette={fallbackColors} />
                  )}
                </div>
              </div>
            </div>

            {fontsAssets.length > 0 && (
              <div className="mt-4 pt-4 border-t border-gray-100">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold">
                    Bundled brand fonts
                  </div>
                  <span className="text-[10px] text-gray-400 font-mono">
                    {fontsAssets.length} file{fontsAssets.length === 1 ? "" : "s"}
                  </span>
                </div>
                <ul className="flex flex-wrap gap-1.5">
                  {fontsAssets.map((f, i) => (
                    <li
                      key={i}
                      title={f.filename}
                      className="px-2 py-1 rounded-md bg-amber-50 ring-1 ring-amber-100 text-amber-800 text-[11px] font-medium leading-tight flex items-center gap-1"
                    >
                      <span>{f.family}</span>
                      <span className="font-mono text-amber-600 text-[10px]">
                        {f.weight}
                      </span>
                      {f.style === "italic" && (
                        <span className="italic text-amber-600 text-[10px]">italic</span>
                      )}
                    </li>
                  ))}
                </ul>
                <p className="text-[10px] text-gray-400 mt-2 leading-relaxed">
                  These fonts are bundled with the master and persist alongside the source .pptx in storage.
                </p>
              </div>
            )}

            {missingBrandFonts.length > 0 && (
              <div className="mt-4 pt-4 border-t border-gray-100">
                <div className="flex items-start gap-2">
                  <AlertCircle size={14} className="text-amber-600 shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-semibold text-gray-700 mb-1">
                      Brand fonts referenced but not bundled
                    </div>
                    <ul className="flex flex-wrap gap-1 mb-1.5">
                      {missingBrandFonts.map((name, i) => (
                        <li
                          key={i}
                          className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 text-[10px] font-medium ring-1 ring-amber-100"
                        >
                          {name}
                        </li>
                      ))}
                    </ul>
                    <p className="text-[10px] text-gray-500 leading-relaxed">
                      These fonts appear in the master's theme but aren't uploaded as files. Re-upload the master with the matching .ttf / .otf files attached so previews and exports render with the correct typography. System fonts (Arial, Calibri, Georgia, …) don't need bundling.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {masterIndices.length > 3 && (
            <div className="mb-4 flex items-center gap-1.5 text-[11px] overflow-x-auto">
              <FilterChip
                active={masterFilter === "all"}
                onClick={() => setMasterFilter("all")}
              >
                All ({layoutCount})
              </FilterChip>
              {masterIndices.map((idx) => {
                const count = m.layouts.filter(
                  (l) => l.master_index === idx,
                ).length;
                return (
                  <FilterChip
                    key={idx}
                    active={masterFilter === String(idx)}
                    onClick={() => setMasterFilter(String(idx))}
                  >
                    Master {idx} ({count})
                  </FilterChip>
                );
              })}
            </div>
          )}

          {m.loading && m.layouts.length === 0 ? (
            <div className="text-center py-16 text-gray-400 text-sm">
              Loading layouts…
            </div>
          ) : m.layouts.length === 0 ? (
            <div className="text-center py-16 text-gray-400 text-sm">
              No layouts on this master.
            </div>
          ) : (
            <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {visibleLayouts.map((layout) => {
                const repeats =
                  shapeRepeatCounts[
                    `${layout.name}${layout.auto_kind}`
                  ] || 1;
                return (
                  <LayoutCard
                    key={layout.id}
                    layout={layout}
                    repeatCount={repeats}
                    busy={busyId === layout.id}
                    onPatch={(patch) => onPatch(layout.id, patch)}
                    onMarkDefault={() => onMarkDefault(layout.id)}
                  />
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, hint }) {
  return (
    <div>
      <div className="text-gray-400 uppercase tracking-wider text-[9px] font-semibold mb-1">
        {label}
      </div>
      <div className="text-gray-700 truncate">{value}</div>
      {hint && (
        <div className="text-[10px] text-gray-400 mt-0.5">{hint}</div>
      )}
    </div>
  );
}

function PaletteSwatches({ palette, title }) {
  return (
    <div className="flex items-center gap-1" title={title}>
      {["primary", "secondary", "text", "bg"].map((k) => (
        <div
          key={k}
          title={`${k}: ${palette[k] || "?"}`}
          className="w-5 h-5 rounded-full ring-1 ring-black/5"
          style={{
            background:
              typeof palette[k] === "string" ? palette[k] : "#ffffff",
          }}
        />
      ))}
    </div>
  );
}

function FilterChip({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`h-7 px-3 rounded-full whitespace-nowrap font-medium transition-colors cursor-pointer ${
        active
          ? "bg-brand text-white"
          : "bg-white ring-1 ring-gray-200 text-gray-600 hover:bg-gray-50"
      }`}
    >
      {children}
    </button>
  );
}
