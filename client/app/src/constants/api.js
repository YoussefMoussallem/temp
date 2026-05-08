// HTTP path prefixes. Relative — the Vite dev server proxy and production
// reverse proxy both handle the origin.
export const API_BASE = "/api";
export const AGENT_BASE = "/api/agent";

// SSE event names emitted by POST /api/agent/turn. Kept in one place so a
// typo in the string literal stays in one place.
export const SSE_EVENTS = Object.freeze({
  STREAM_START: "stream_start",
  TEXT_DELTA: "text_delta",
  TEXT: "text",
  THINKING_DELTA: "thinking_delta",
  WEB_SEARCH_START: "web_search_start",
  WEB_SEARCH_DONE: "web_search_done",
  TOOL_CALL_START: "tool_call_start",
  TOOL_CALL_DONE: "tool_call_done",
  TOOL_REQUEST: "tool_request",
  ASSISTANT_MESSAGE: "assistant_message",
  STATE_UPDATE: "state_update",
  DONE: "done",
  ERROR: "error",
  SLIDE_CREATED: "slide_created",
  SLIDE_UPDATED: "slide_updated",
  SLIDE_DELETED: "slide_deleted",
  SLIDES_REPLACED: "slides_replaced",
});
