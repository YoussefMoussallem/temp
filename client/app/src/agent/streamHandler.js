// Pure dispatcher for SSE events from streamTurn. Takes one event and a
// set of optional callbacks, routes by event type. State lives in the
// caller — this file doesn't own any.
//
// Unknown event types fall through to `onUnknown` so callers (e.g. a deck
// reducer listening to slide_* events) can handle new events without
// modifying this switch.

export function handleStreamEvent(event, callbacks) {
  const { event: type, data } = event;
  switch (type) {
    case "thinking_delta":
      callbacks.onThinkingDelta?.(data.text || "");
      break;
    case "web_search_start":
      callbacks.onSearchStart?.(data.query || "");
      break;
    case "web_search_done":
      callbacks.onSearchDone?.(data.result || "");
      break;
    case "tool_call_start":
      callbacks.onToolCallStart?.({
        name: data.name || "",
        callId: data.call_id || data.id || "",
      });
      break;
    case "tool_call_done":
      callbacks.onToolCallDone?.({
        name: data.name || "",
        callId: data.call_id || data.id || "",
        arguments: data.arguments,
      });
      break;
    case "tool_request":
      callbacks.onToolRequest?.(data);
      break;
    case "tool_progress":
      callbacks.onToolProgress?.(data.tool_use_id || "", data.data);
      break;
    case "assistant_message":
      callbacks.onAssistantMessage?.(data.message || null);
      break;
    case "state_update":
      callbacks.onStateUpdate?.(data.state || {});
      break;
    case "text_delta":
      callbacks.onTextDelta?.(data.text || "");
      break;
    case "text":
      callbacks.onText?.(data.text || "");
      break;
    case "done":
      callbacks.onDone?.({
        usage: data.usage || null,
        stopReason: data.stop_reason || "",
      });
      break;
    case "error":
      callbacks.onError?.(data.message || "Unknown error");
      break;
    case "command_lifecycle":
      callbacks.onCommandLifecycle?.(data.uuid || "", data.state || "");
      break;
    case "user_message":
      callbacks.onUserMessage?.(data.message || null);
      break;
    case "compact_boundary":
      // Backend emits this when the compaction pipeline (autocompact
      // threshold or manual /compact) summarised earlier history.
      // The payload mirrors the `CompactBoundary` dataclass; we
      // forward it as-is so the component can render its fields.
      callbacks.onCompactBoundary?.(data.boundary || null);
      break;
    case "compact_warning":
      // Backend's compact_warning_hook fired (context >=70% full).
      // Payload is a serialized `WarningState` dataclass.
      callbacks.onCompactWarning?.(data.warning || null);
      break;
    case "slide_created":
    case "slide_updated":
    case "slide_deleted":
    case "slides_replaced":
      callbacks.onSlideEvent?.(type, data);
      break;
    case "deck_export_ready":
      callbacks.onDeckExportReady?.(data);
      break;
    case "deck_export_dom_ready":
      callbacks.onDeckExportDomReady?.(data);
      break;
    default:
      callbacks.onUnknown?.(type, data);
      break;
  }
}
