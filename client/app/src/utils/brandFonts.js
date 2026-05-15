// Brand-font reconciliation between manifest.fonts_referenced and
// uploaded fonts_assets.
//
// fonts_referenced lists every typeface name the .pptx mentions
// (master theme major/minor + per-placeholder rPr fonts). fonts_assets
// is what the user actually uploaded as bundled .ttf/.otf files.
//
// The gap (referenced − bundled − system fallbacks) is the set of
// brand fonts the user still needs to attach. System fonts are
// available everywhere and don't need bundling, so we exclude them
// from the missing list.

const SYSTEM_FONT_NAMES = new Set([
  "arial",
  "arial unicode ms",
  "helvetica",
  "calibri",
  "calibri light",
  "cambria",
  "consolas",
  "courier",
  "courier new",
  "georgia",
  "lucida sans",
  "segoe ui",
  "tahoma",
  "times",
  "times new roman",
  "trebuchet ms",
  "verdana",
]);

export function isSystemFontName(name) {
  return SYSTEM_FONT_NAMES.has((name || "").trim().toLowerCase());
}

export function computeMissingBrandFonts(fontsReferenced, fontsAssets) {
  const referenced = Array.isArray(fontsReferenced) ? fontsReferenced : [];
  const assets = Array.isArray(fontsAssets) ? fontsAssets : [];
  const bundled = new Set(
    assets.map((f) => (f.family || "").trim().toLowerCase()),
  );
  return referenced.filter((name) => {
    const norm = (name || "").trim().toLowerCase();
    if (!norm) return false;
    if (SYSTEM_FONT_NAMES.has(norm)) return false;
    return !bundled.has(norm);
  });
}
