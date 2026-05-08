// DOM-driven .pptx assembler. This experimental path exports from the
// already-rendered slide HTML instead of asking the backend to translate each
// slide through an LLM first.

import PptxGenJS from "pptxgenjs";

const SLIDE_WIDTH_PX = 960;
const SLIDE_HEIGHT_PX = 540;

function ensurePptxExtension(name) {
  const trimmed = (name || "").trim() || "presentation-dom";
  return /\.pptx$/i.test(trimmed) ? trimmed : `${trimmed}.pptx`;
}

function sortedSlides(slides) {
  return [...(slides || [])]
    .filter((slide) => slide?.html)
    .sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
}

function waitForLayout() {
  return new Promise((resolve) => {
    const settle = () => requestAnimationFrame(() => requestAnimationFrame(resolve));
    if (document.fonts?.ready && typeof document.fonts.ready.then === "function") {
      document.fonts.ready.then(settle).catch(settle);
    } else {
      settle();
    }
  });
}

async function loadExporter() {
  if (typeof window === "undefined" || typeof document === "undefined") {
    throw new Error("DOM export can only run in a browser.");
  }

  // The upstream package is an IIFE that looks up PptxGenJS on window.
  if (!window.PptxGenJS) window.PptxGenJS = PptxGenJS;
  await import("llm-dom-to-pptx");

  const exporter = window.LLMDomToPptx?.export;
  if (typeof exporter !== "function") {
    throw new Error("llm-dom-to-pptx did not expose LLMDomToPptx.export.");
  }
  return exporter;
}

function cloneSafeNode(node) {
  if (node.nodeType === Node.ELEMENT_NODE && node.tagName === "SCRIPT") return null;
  return node.cloneNode(true);
}

function buildOffscreenSlide(html) {
  const parsed = new DOMParser().parseFromString(html || "", "text/html");
  const mount = document.createElement("div");
  mount.style.cssText = [
    "position:fixed",
    "left:-10000px",
    "top:0",
    `width:${SLIDE_WIDTH_PX}px`,
    `height:${SLIDE_HEIGHT_PX}px`,
    "overflow:hidden",
    "visibility:visible",
    "pointer-events:none",
    "background:#ffffff",
    "z-index:-1",
  ].join(";");

  for (const style of parsed.head.querySelectorAll("style")) {
    mount.appendChild(style.cloneNode(true));
  }

  for (const node of parsed.body.childNodes) {
    const clone = cloneSafeNode(node);
    if (clone) mount.appendChild(clone);
  }

  const firstVisualElement = Array.from(mount.children).find(
    (child) => child.tagName !== "STYLE",
  );
  const target = mount.querySelector(".slide") || firstVisualElement || mount;
  if (target instanceof HTMLElement) {
    if (!target.style.width) target.style.width = `${SLIDE_WIDTH_PX}px`;
    if (!target.style.height) target.style.height = `${SLIDE_HEIGHT_PX}px`;
    if (!target.style.position) target.style.position = "relative";
    if (!target.style.overflow) target.style.overflow = "hidden";
  }

  return { mount, target };
}

function createSharedPptx(filename) {
  const pptx = new PptxGenJS();
  pptx.title = filename.replace(/\.pptx$/i, "");

  const originalWriteFile = pptx.writeFile.bind(pptx);
  pptx.writeFile = async () => {};

  function SharedPptxGenJS() {
    return pptx;
  }

  return {
    pptx,
    SharedPptxGenJS,
    restoreWriteFile() {
      pptx.writeFile = originalWriteFile;
    },
  };
}

/**
 * Export stored slide HTML directly through llm-dom-to-pptx.
 *
 * @param {object} args
 * @param {Array<object>} args.slides deck slides from DeckContext
 * @param {string} [args.filename]
 * @param {(progress: {phase: string, current?: number, total?: number}) => void} [args.onProgress]
 * @returns {Promise<string>} the filename actually written
 */
export async function buildAndDownloadDomPptx({
  slides,
  filename = "presentation-dom.pptx",
  onProgress,
} = {}) {
  const exportSlides = sortedSlides(slides);
  if (exportSlides.length === 0) {
    throw new Error("No slides to export.");
  }

  const finalFilename = ensurePptxExtension(filename);
  const exporter = await loadExporter();
  const previousPptxGen = window.PptxGenJS;
  const { pptx, SharedPptxGenJS, restoreWriteFile } = createSharedPptx(finalFilename);

  window.PptxGenJS = SharedPptxGenJS;

  try {
    const total = exportSlides.length;
    for (let i = 0; i < total; i++) {
      onProgress?.({ phase: "render", current: i, total });
      const { mount, target } = buildOffscreenSlide(exportSlides[i].html);
      document.body.appendChild(mount);
      try {
        await waitForLayout();
        await exporter(target, { fileName: finalFilename });
      } finally {
        mount.remove();
      }
      onProgress?.({ phase: "render", current: i + 1, total });
    }

    onProgress?.({ phase: "write", current: total, total });
    restoreWriteFile();
    await pptx.writeFile({ fileName: finalFilename });
    onProgress?.({ phase: "done", current: total, total });
  } finally {
    window.PptxGenJS = previousPptxGen;
    restoreWriteFile();
  }

  return finalFilename;
}
