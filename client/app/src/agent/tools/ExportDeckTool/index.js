// ExportDeck is a backend-driven tool — no frontend UI component. The
// backend converts each slide's HTML to a pptxgenjs JSON spec via LLM
// and emits a `deck_export_ready` SSE event. useChat picks that up and
// calls `buildAndDownloadPptx` here.

export { buildAndDownloadPptx } from "./buildPptx.js";
export { buildAndDownloadDomPptx } from "./buildDomPptx.js";
export const TOOL_NAME = "ExportDeck";
