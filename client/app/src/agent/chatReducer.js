// Chat reducer — the single state container for everything useChat owns.
//
// Pattern ported from RevitCode's `state/messageReducer.js`, scaled down
// to one flat file because Edwin's surface is smaller (no subagents, no
// permission queue, no task store) — splitting into domain reducers
// would be premature.
//
// Every state transition the chat needs goes through here. Stream
// events arrive via SSE → `streamHandler.js` → action dispatch. User
// actions (clicks, sends) also go through dispatch. The hook
// (`useChat.js`) provides a thin React wrapper + escape hatches for
// async work that needs `getState` semantics (the orchestrator in
// `agentLoop.js` uses those).
//
// No React imports here — keep it pure so it's trivially testable and
// usable from non-component contexts (the loop dispatches through a
// `dispatch` callback passed in).

// ─── Initial state pieces ───────────────────────────────────────────────────

export const INITIAL_STREAM = {
  thinkingText: "",
  fullText: "",
  searches: [],
  toolCalls: [],
  // Ordered block accumulator — the renderer for both streaming and
  // persisted assistant messages reads from here.
  // Each entry is one of:
  //   { type: "thinking", text, active }
  //   { type: "search",   id, query, result, active }
  //   { type: "tool",     id, name, active, progress }
  //   { type: "text",     text }
  blocks: [],
  usage: null,
  stopReason: "",
};

export const INITIAL_CLIENT_STATE = {
  model: "",
  iteration: 0,
  extra: {},
  permission_mode: "default",
};

export const INITIAL_TOTAL_USAGE = {
  inputTokens: 0,
  outputTokens: 0,
  requests: 0,
};

export const INITIAL_STATE = {
  messages: [],
  loadingHistory: false,
  busy: false,
  stream: INITIAL_STREAM,
  pendingToolRequest: null,
  todos: [],
  error: null,
  clientState: INITIAL_CLIENT_STATE,
  totalUsage: INITIAL_TOTAL_USAGE,
  compactWarning: null,
  warningDismissedAt: null,
};

// ─── Block-list helpers — immutable updates on stream.blocks ─────────────

function lastBlock(blocks) {
  return blocks.length ? blocks[blocks.length - 1] : null;
}

function sealOpenThinking(blocks) {
  // When a non-thinking block starts arriving, seal any in-flight
  // thinking block so the renderer stops showing it as live.
  let mutated = false;
  const next = blocks.map((b) => {
    if (b.type === "thinking" && b.active) {
      mutated = true;
      return { ...b, active: false };
    }
    return b;
  });
  return mutated ? next : blocks;
}

function appendThinking(blocks, text) {
  const last = lastBlock(blocks);
  if (last && last.type === "thinking" && last.active) {
    return [
      ...blocks.slice(0, -1),
      { ...last, text: last.text + text },
    ];
  }
  return [...blocks, { type: "thinking", text, active: true }];
}

function appendText(blocks, text) {
  const last = lastBlock(blocks);
  if (last && last.type === "text") {
    return [
      ...blocks.slice(0, -1),
      { ...last, text: last.text + text },
    ];
  }
  return [...blocks, { type: "text", text }];
}

function replaceTrailingText(blocks, text) {
  const last = lastBlock(blocks);
  if (last && last.type === "text") {
    return [...blocks.slice(0, -1), { ...last, text }];
  }
  return [...blocks, { type: "text", text }];
}

function pushSearch(blocks, query) {
  const sealed = sealOpenThinking(blocks);
  const id = `s${sealed.length}`;
  return [
    ...sealed,
    { type: "search", id, query, result: "", active: true },
  ];
}

function finishLastActiveSearch(blocks, result) {
  for (let i = blocks.length - 1; i >= 0; i--) {
    if (blocks[i].type === "search" && blocks[i].active) {
      const next = [...blocks];
      next[i] = { ...next[i], active: false, result };
      return next;
    }
  }
  return blocks;
}

function pushTool(blocks, id, name) {
  const sealed = sealOpenThinking(blocks);
  return [
    ...sealed,
    { type: "tool", id, name, active: true, progress: null },
  ];
}

function updateTool(blocks, id, patch) {
  let mutated = false;
  const next = blocks.map((b) => {
    if (b.type === "tool" && b.id === id) {
      mutated = true;
      return { ...b, ...patch };
    }
    return b;
  });
  return mutated ? next : blocks;
}

function sealActiveTools(blocks) {
  let mutated = false;
  const next = blocks.map((b) => {
    if (b.type === "tool" && b.active) {
      mutated = true;
      return { ...b, active: false };
    }
    return b;
  });
  return mutated ? next : blocks;
}

// ─── Action types ───────────────────────────────────────────────────────────

// Grouped by life-cycle to keep the switch readable. Centralised here so a
// typo at a dispatch site fails the import rather than silently no-op'ing.

export const A = Object.freeze({
  // History / conversation
  HYDRATE_HISTORY_START: "HYDRATE_HISTORY_START",
  HYDRATE_HISTORY_DONE: "HYDRATE_HISTORY_DONE",
  HYDRATE_HISTORY_ERROR: "HYDRATE_HISTORY_ERROR",
  CONVERSATION_RESET: "CONVERSATION_RESET",
  CLEAR_CONVERSATION: "CLEAR_CONVERSATION",
  MESSAGES_REPLACE: "MESSAGES_REPLACE",
  MESSAGES_PREPEND: "MESSAGES_PREPEND",

  // Turn lifecycle
  TURN_START: "TURN_START",
  TURN_DONE: "TURN_DONE",
  TURN_ERROR: "TURN_ERROR",

  // Stream events (per-event reducer updates)
  STREAM_RESET: "STREAM_RESET",
  THINKING_DELTA: "THINKING_DELTA",
  TEXT_DELTA: "TEXT_DELTA",
  TEXT_REPLACE: "TEXT_REPLACE",
  SEARCH_START: "SEARCH_START",
  SEARCH_DONE: "SEARCH_DONE",
  TOOL_CALL_START: "TOOL_CALL_START",
  TOOL_CALL_DONE: "TOOL_CALL_DONE",
  TOOL_CALL_COMPLETE: "TOOL_CALL_COMPLETE",
  TOOL_PROGRESS: "TOOL_PROGRESS",
  STREAM_DONE: "STREAM_DONE",

  // Interactive tool handoff
  TOOL_REQUEST_SET: "TOOL_REQUEST_SET",
  TOOL_REQUEST_CLEAR: "TOOL_REQUEST_CLEAR",

  // Backend message inbound (assistant_message, user_message stdout, etc.)
  USER_MESSAGE_APPEND: "USER_MESSAGE_APPEND",
  ASSISTANT_MESSAGE_APPEND: "ASSISTANT_MESSAGE_APPEND",
  COMMAND_LIFECYCLE_UPDATE: "COMMAND_LIFECYCLE_UPDATE",
  COMPACT_BOUNDARY_APPEND: "COMPACT_BOUNDARY_APPEND",

  // Backend opaque state
  CLIENT_STATE_PATCH: "CLIENT_STATE_PATCH",
  CLIENT_STATE_REPLACE: "CLIENT_STATE_REPLACE",
  USAGE_ACCUMULATE: "USAGE_ACCUMULATE",

  // Compact warning surface
  COMPACT_WARNING_SET: "COMPACT_WARNING_SET",
  COMPACT_WARNING_DISMISS: "COMPACT_WARNING_DISMISS",

  // Todos
  TODOS_SET: "TODOS_SET",

  // Errors
  ERROR_SET: "ERROR_SET",
  ERROR_CLEAR: "ERROR_CLEAR",
});

// ─── Reducer ────────────────────────────────────────────────────────────────

export function chatReducer(state, action) {
  switch (action.type) {
    // ── History / conversation ────────────────────────────────────────────

    case A.HYDRATE_HISTORY_START:
      return { ...state, loadingHistory: true, error: null };

    case A.HYDRATE_HISTORY_DONE: {
      const { messages, permission_mode } = action.payload || {};
      return {
        ...state,
        messages: Array.isArray(messages) ? messages : [],
        clientState: {
          ...INITIAL_CLIENT_STATE,
          permission_mode: permission_mode ?? "default",
        },
        stream: INITIAL_STREAM,
        loadingHistory: false,
        error: null,
      };
    }

    case A.HYDRATE_HISTORY_ERROR:
      return {
        ...state,
        loadingHistory: false,
        error: action.payload?.message ?? "Failed to load history",
      };

    case A.CONVERSATION_RESET:
      // Triggered when conversationId becomes null. Drop everything.
      return {
        ...INITIAL_STATE,
        loadingHistory: false,
      };

    case A.CLEAR_CONVERSATION:
      // /clear and friends. Wipe in-memory chat but keep plan-mode so
      // the user's current permission stance survives.
      return {
        ...INITIAL_STATE,
        clientState: {
          ...INITIAL_CLIENT_STATE,
          permission_mode: state.clientState.permission_mode,
        },
        loadingHistory: false,
      };

    case A.MESSAGES_REPLACE:
      return {
        ...state,
        messages: Array.isArray(action.payload?.messages)
          ? action.payload.messages
          : [],
        stream: INITIAL_STREAM,
        totalUsage: INITIAL_TOTAL_USAGE,
        todos: [],
        // /clear and history refetch land here; this is the natural
        // closer of any in-flight history load, so clearing the flag
        // saves callers a follow-up HYDRATE_HISTORY_DONE that would
        // race a stale stateRef snapshot.
        loadingHistory: false,
      };

    case A.MESSAGES_PREPEND:
      return {
        ...state,
        messages: [
          ...(action.payload?.messages || []),
          ...state.messages,
        ],
      };

    // ── Turn lifecycle ────────────────────────────────────────────────────

    case A.TURN_START:
      return {
        ...state,
        busy: true,
        error: null,
        stream: INITIAL_STREAM,
      };

    case A.TURN_DONE:
      return {
        ...state,
        busy: false,
      };

    case A.TURN_ERROR:
      return {
        ...state,
        busy: false,
        error: action.payload?.message ?? "Network error",
      };

    // ── Stream events ─────────────────────────────────────────────────────
    //
    // Each per-event action returns minimal new state. The renderer reads
    // ``stream.blocks`` for ordered display + ``stream.fullText`` for
    // post-stream meta — both stay in sync because every text-emitting
    // action updates both.

    case A.STREAM_RESET:
      return { ...state, stream: INITIAL_STREAM };

    case A.THINKING_DELTA: {
      const text = action.payload?.text || "";
      return {
        ...state,
        stream: {
          ...state.stream,
          thinkingText: state.stream.thinkingText + text,
          blocks: appendThinking(state.stream.blocks, text),
        },
      };
    }

    case A.TEXT_DELTA: {
      const text = action.payload?.text || "";
      return {
        ...state,
        stream: {
          ...state.stream,
          fullText: state.stream.fullText + text,
          blocks: appendText(state.stream.blocks, text),
        },
      };
    }

    case A.TEXT_REPLACE: {
      const text = action.payload?.text || "";
      return {
        ...state,
        stream: {
          ...state.stream,
          fullText: text,
          blocks: replaceTrailingText(state.stream.blocks, text),
        },
      };
    }

    case A.SEARCH_START: {
      const query = action.payload?.query || "";
      return {
        ...state,
        stream: {
          ...state.stream,
          searches: [
            ...state.stream.searches,
            { active: true, query, result: "" },
          ],
          blocks: pushSearch(state.stream.blocks, query),
        },
      };
    }

    case A.SEARCH_DONE: {
      const result = action.payload?.result || "";
      const searches = state.stream.searches.length
        ? [
            ...state.stream.searches.slice(0, -1),
            {
              ...state.stream.searches[state.stream.searches.length - 1],
              active: false,
              result,
            },
          ]
        : state.stream.searches;
      return {
        ...state,
        stream: {
          ...state.stream,
          searches,
          blocks: finishLastActiveSearch(state.stream.blocks, result),
        },
      };
    }

    case A.TOOL_CALL_START: {
      const { id, name } = action.payload || {};
      const toolCalls = [
        ...state.stream.toolCalls.map((tc) => ({ ...tc, active: false })),
        { id, name, active: true },
      ];
      return {
        ...state,
        stream: {
          ...state.stream,
          toolCalls,
          blocks: pushTool(state.stream.blocks, id, name),
        },
      };
    }

    case A.TOOL_CALL_DONE: {
      // ``tool_call_done`` from the model SDK only marks the model
      // having finished emitting the tool_use block — the tool
      // itself doesn't start running until the assistant stream ends.
      // Leave ``active`` alone; the real "tool finished" signal comes
      // from the backend as TOOL_CALL_COMPLETE below.
      return state;
    }

    case A.TOOL_CALL_COMPLETE: {
      // Backend signal: this specific tool finished executing. Seal
      // its spinner.
      const { id } = action.payload || {};
      return {
        ...state,
        stream: {
          ...state.stream,
          blocks: updateTool(state.stream.blocks, id, { active: false }),
        },
      };
    }

    case A.TOOL_PROGRESS: {
      const { id, progress } = action.payload || {};
      return {
        ...state,
        stream: {
          ...state.stream,
          toolCalls: state.stream.toolCalls.map((tc) =>
            tc.id === id ? { ...tc, progress } : tc,
          ),
          blocks: updateTool(state.stream.blocks, id, { progress }),
        },
      };
    }

    case A.STREAM_DONE: {
      // Final cleanup pass — seal any in-flight thinking block and
      // any tool blocks that didn't get a TOOL_CALL_COMPLETE (e.g.
      // interactive tools that exit via ``tool_request`` rather than
      // running to a tool_result, or aborted legs). Belt-and-
      // suspenders against forever-spinning indicators.
      const { usage, stopReason } = action.payload || {};
      return {
        ...state,
        stream: {
          ...state.stream,
          blocks: sealActiveTools(sealOpenThinking(state.stream.blocks)),
          usage: usage ?? state.stream.usage,
          stopReason: stopReason ?? state.stream.stopReason,
        },
      };
    }

    // ── Interactive tool handoff ──────────────────────────────────────────

    case A.TOOL_REQUEST_SET:
      return { ...state, pendingToolRequest: action.payload?.req ?? null };

    case A.TOOL_REQUEST_CLEAR:
      return { ...state, pendingToolRequest: null };

    // ── Messages ──────────────────────────────────────────────────────────

    case A.USER_MESSAGE_APPEND: {
      const msg = action.payload?.message;
      if (!msg) return state;
      return { ...state, messages: [...state.messages, msg] };
    }

    case A.ASSISTANT_MESSAGE_APPEND: {
      const msg = action.payload?.message;
      if (!msg) return state;
      return {
        ...state,
        messages: [...state.messages, msg],
        clientState: {
          ...state.clientState,
          iteration: state.clientState.iteration + 1,
        },
      };
    }

    case A.COMMAND_LIFECYCLE_UPDATE: {
      const { uuid, state: cmdState } = action.payload || {};
      if (!uuid) return state;
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.commandUuid === uuid ? { ...m, commandState: cmdState } : m,
        ),
      };
    }

    case A.COMPACT_BOUNDARY_APPEND: {
      const boundary = action.payload?.boundary;
      if (!boundary) return state;
      return {
        ...state,
        messages: [...state.messages, { role: "compact-boundary", boundary }],
      };
    }

    // ── Backend opaque state ──────────────────────────────────────────────

    case A.CLIENT_STATE_PATCH:
      return {
        ...state,
        clientState: { ...state.clientState, ...(action.payload || {}) },
      };

    case A.CLIENT_STATE_REPLACE:
      return {
        ...state,
        clientState: { ...INITIAL_CLIENT_STATE, ...(action.payload || {}) },
      };

    case A.USAGE_ACCUMULATE: {
      const u = action.payload?.usage;
      if (!u) return state;
      return {
        ...state,
        totalUsage: {
          inputTokens: state.totalUsage.inputTokens + (u.input_tokens || 0),
          outputTokens: state.totalUsage.outputTokens + (u.output_tokens || 0),
          requests: state.totalUsage.requests + 1,
        },
      };
    }

    // ── Compact warning surface ───────────────────────────────────────────

    case A.COMPACT_WARNING_SET: {
      const warning = action.payload?.warning;
      if (!warning) return state;
      // Re-arm dismissal if the new warning's fill_pct is *higher* than
      // where we last dismissed — matches source's "show again on next
      // threshold cross" requirement.
      const prevDismissed = state.warningDismissedAt;
      const warningDismissedAt =
        prevDismissed !== null && (warning.fill_pct ?? 0) > prevDismissed
          ? null
          : prevDismissed;
      return { ...state, compactWarning: warning, warningDismissedAt };
    }

    case A.COMPACT_WARNING_DISMISS:
      return {
        ...state,
        warningDismissedAt: state.compactWarning?.fill_pct ?? 0,
      };

    // ── Todos ─────────────────────────────────────────────────────────────

    case A.TODOS_SET:
      return { ...state, todos: action.payload?.todos ?? [] };

    // ── Errors ────────────────────────────────────────────────────────────

    case A.ERROR_SET:
      return { ...state, error: action.payload?.message ?? null };

    case A.ERROR_CLEAR:
      return { ...state, error: null };

    default:
      return state;
  }
}

// ─── Computed selectors ─────────────────────────────────────────────────────
//
// Pure derivations consumers need. Kept here so the calling hook doesn't
// re-implement them.

export function compactWarningVisible(state) {
  const w = state.compactWarning;
  if (!w?.should_show) return false;
  if (state.warningDismissedAt === null) return true;
  return (w.fill_pct ?? 0) > state.warningDismissedAt;
}
