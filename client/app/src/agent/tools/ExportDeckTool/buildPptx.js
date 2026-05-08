// Spec-driven .pptx assembler. Consumes the JSON deck spec produced by
// the backend ExportDeck tool (which itself is the LLM-converted form of
// each slide's HTML) and writes a fully editable .pptx using pptxgenjs.
//
// Spec shape (must match server/.../ExportDeckTool/prompt.py):
//
//   {
//     filename: "presentation.pptx",
//     layout: "LAYOUT_WIDE",
//     slides: [
//       {
//         id, position, title,
//         spec: {
//           background: { color: "RRGGBB" } | null,
//           elements: [
//             { kind: "text",  text, options: {...} },
//             { kind: "shape", shape: "rect"|"roundRect"|"ellipse"|"line", options: {...} },
//             { kind: "image", options: { path|data, x, y, w, h } },
//           ]
//         }
//       },
//       ...
//     ]
//   }
//
// Why client-side: pptxgenjs is a browser/node library. Running it in
// the browser means the .pptx blob never touches the backend disk and
// downloads with zero extra round-trips.

import PptxGenJS from "pptxgenjs";

function ensurePptxExtension(name) {
  const trimmed = (name || "").trim() || "presentation";
  return /\.pptx$/i.test(trimmed) ? trimmed : `${trimmed}.pptx`;
}

// pptxgenjs's `addShape` enum lives at runtime on the instance. We pass
// the string name through; pptxgenjs accepts these names directly. This
// map exists to validate against the LLM emitting nonsense.
const ALLOWED_SHAPES = new Set([
  "rect",
  "roundRect",
  "ellipse",
  "line",
  "triangle",
  "diamond",
]);

// Strip any "#" prefix the LLM might add despite the prompt forbidding it.
function normalizeColor(value) {
  if (typeof value !== "string") return undefined;
  const v = value.replace(/^#/, "").trim();
  return /^[0-9a-fA-F]{6}$/.test(v) ? v.toUpperCase() : undefined;
}

// pptxgenjs accepts color either as a string or as { color, transparency }.
// Recursively normalize colors inside `fill` and `line` so the LLM can
// emit either form.
function normalizeOptions(opts) {
  if (!opts || typeof opts !== "object") return {};
  const out = { ...opts };

  if (typeof out.color === "string") {
    const c = normalizeColor(out.color);
    if (c) out.color = c;
  }
  if (out.fill && typeof out.fill === "object") {
    const c = normalizeColor(out.fill.color);
    out.fill = c ? { ...out.fill, color: c } : out.fill;
  }
  if (out.line && typeof out.line === "object" && out.line.color) {
    const c = normalizeColor(out.line.color);
    out.line = c ? { ...out.line, color: c } : out.line;
  }

  return out;
}

function applyBackground(slide, background) {
  if (!background) return;
  const color = normalizeColor(background.color);
  if (color) slide.background = { color };
}

function applyElement(slide, el) {
  if (!el || typeof el !== "object") return;
  const opts = normalizeOptions(el.options);

  if (el.kind === "text") {
    const text = typeof el.text === "string" ? el.text : "";
    if (!text) return;
    slide.addText(text, opts);
    return;
  }

  if (el.kind === "shape") {
    const shape = ALLOWED_SHAPES.has(el.shape) ? el.shape : "rect";
    slide.addShape(shape, opts);
    return;
  }

  if (el.kind === "image") {
    if (!opts.path && !opts.data) return;
    slide.addImage(opts);
  }
}

/**
 * Assemble a .pptx from a deck spec and trigger the browser download.
 *
 * @param {object} deck       deck spec from `deck_export_ready`
 * @param {(progress: {phase: string, current?: number, total?: number}) => void} [onProgress]
 * @returns {Promise<string>} the filename actually written
 */
export async function buildAndDownloadPptx(deck, onProgress) {
  if (!deck || !Array.isArray(deck.slides) || deck.slides.length === 0) {
    throw new Error("Deck spec is empty — nothing to export.");
  }

  const filename = ensurePptxExtension(deck.filename);
  const pptx = new PptxGenJS();
  pptx.layout = deck.layout || "LAYOUT_WIDE";
  pptx.title = filename.replace(/\.pptx$/i, "");

  const total = deck.slides.length;
  for (let i = 0; i < total; i++) {
    const slideSpec = deck.slides[i]?.spec || {};
    onProgress?.({ phase: "assemble", current: i, total });

    const slide = pptx.addSlide();
    applyBackground(slide, slideSpec.background);
    const elements = Array.isArray(slideSpec.elements) ? slideSpec.elements : [];
    for (const el of elements) {
      try {
        applyElement(slide, el);
      } catch (err) {
        // One bad element shouldn't tank the whole deck. Log and skip.
        // eslint-disable-next-line no-console
        console.warn("ExportDeck: skipped malformed element", { el, err });
      }
    }
  }

  onProgress?.({ phase: "write", current: total, total });
  await pptx.writeFile({ fileName: filename });
  onProgress?.({ phase: "done", current: total, total });

  return filename;
}
