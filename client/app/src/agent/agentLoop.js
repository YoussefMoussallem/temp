// agentLoop.js — single-function orchestrator for one logical turn.
//
// Ported from RevitCode's `agent/agentLoop.js`, adapted to Edwin's
// surface (no FE-side persistence, two interactive tool types instead
// of an open set, no subagents).
//
// What this replaces in the old useChat.js:
//
//   - `send` / `advanceBatch` / `submitToolAnswer` / `submitPlanAnswer`
//     each called `processStream` once per FE-initiated leg.
//   - State drift between legs was patched with `activeStreamRef` and
//     `deferredToolRequest` band-aids.
//
// The new shape: ONE async function (`runTurn`) handles the whole turn
// through a `while` loop. Interactive tool requests are resolved by
// awaiting a promise that user-action handlers in the hook resolve.
// No prior leg can clobber a newer one because there is no second
// `processStream` call to lose track of.
//
// State changes flow exclusively through the `dispatch` callback the
// caller passes in — no React imports here, so this is trivially
// testable and there's a clean seam between "what happened" and "how
// the UI re-renders."

import { streamTurn } from "./client.js";
import { handleStreamEvent } from "./streamHandler.js";
import { A } from "./chatReducer.js";

/**
 * Run one logical turn end-to-end.
 *
 * The caller provides:
 *   - dispatch:           the reducer dispatch function
 *   - initialInput:       { userInput?, toolResults?, commandUuid? }
 *                         The first leg's payload to /turn. Subsequent
 *                         legs are auto-constructed from tool_results.
 *   - conversationId
 *   - projectId
 *   - getToken
 *   - signal:             AbortSignal owned by the caller
 *   - thinking, webSearch (turn-level toggles)
 *   - getAgentState():    callback returning the current opaque
 *                         clientState blob for the next POST. Read
 *                         inside the loop because the reducer may
 *                         mutate it mid-leg (state_update events).
 *   - awaitInteractive(req): callback that surfaces the modal UI for
 *                         a tool_request envelope and returns a
 *                         promise resolving to the user's tool_results
 *                         array. The hook implements this by holding
 *                         a ref-stored resolve fn that
 *                         submitToolAnswer / submitPlanAnswer call.
 *   - onSlideEvent:       optional pass-through to DeckContext.
 *   - notifyCommandUuid:  called once at the start of the turn (when
 *                         the leg includes a slash-command uuid) so
 *                         the caller can attach it to an optimistic
 *                         bubble for lifecycle updates.
 *
 * Returns the terminal `{ stopReason }` so the caller can route
 * `/clear` refetches etc. Errors thrown (other than AbortError) are
 * dispatched as TURN_ERROR and re-thrown so the caller knows to stop.
 */
export async function runTurn({
  dispatch,
  conversationId,
  projectId,
  initialInput,
  getAgentState,
  awaitInteractive,
  getToken,
  signal,
  thinking,
  webSearch,
  onSlideEvent,
  onDeckExportReady,
  onDeckExportDomReady,
  refetchMessages,
}) {
  if (!conversationId) {
    throw new Error("No active conversation");
  }

  // The next leg's request payload. Mutates within the loop: when a
  // tool_request lands, we wait for user response, then set
  // `toolResults` for the next leg's POST. `userInput` is non-null
  // only on the very first leg.
  let userInput = initialInput?.userInput ?? null;
  let toolResults = initialInput?.toolResults ?? [];
  let commandUuid = initialInput?.commandUuid ?? null;
  let agentStateOverride = initialInput?.agentStateOverride ?? null;

  let stopReason = "";

  dispatch({ type: A.TURN_START });

  try {
    while (!signal.aborted) {
      dispatch({ type: A.STREAM_RESET });

      // Run one leg. Side effects: dispatches stream events into the
      // reducer; collects any tool_request envelope; tracks assistant
      // message for after-stream meta.
      const leg = await runLeg({
        dispatch,
        conversationId,
        projectId,
        userInput,
        toolResults,
        commandUuid,
        agentStateOverride: agentStateOverride ?? getAgentState(),
        getToken,
        signal,
        thinking,
        webSearch,
        onSlideEvent,
        onDeckExportReady,
        onDeckExportDomReady,
      });

      stopReason = leg.stopReason;

      // After-leg housekeeping that has to happen regardless of whether
      // we continue or terminate:
      //   - If the model produced an assistant message, persist it
      //     into the message list so it stays visible across the leg
      //     boundary.
      if (leg.assistantMessage || leg.fullText) {
        const persisted = buildPersistedAssistantMessage(leg);
        dispatch({
          type: A.ASSISTANT_MESSAGE_APPEND,
          payload: { message: persisted },
        });
      }

      // ── Branching: tool_request → user input → continuation, or
      //    terminal → done.

      if (leg.toolRequest && !signal.aborted) {
        // Surface the interactive UI and wait for the user. The hook
        // implements awaitInteractive by dispatching TOOL_REQUEST_SET
        // and parking on a promise that the answer-submission
        // handlers resolve.
        const userToolResults = await awaitInteractive(leg.toolRequest);
        if (signal.aborted) break;

        // The interactive handler may have flipped the permission mode
        // (e.g. plan approval → "default"). awaitInteractive returns
        // { results, modeChange }. Apply mode change to the next leg's
        // agentStateOverride so the new permission lands on the same
        // POST that carries the approval.
        if (userToolResults?.modeChange) {
          const next = {
            ...getAgentState(),
            permission_mode: userToolResults.modeChange,
          };
          dispatch({
            type: A.CLIENT_STATE_PATCH,
            payload: { permission_mode: userToolResults.modeChange },
          });
          if (userToolResults.modeChange === "default") {
            dispatch({ type: A.TODOS_SET, payload: { todos: [] } });
          }
          agentStateOverride = next;
        } else {
          agentStateOverride = null;
        }

        userInput = null;
        toolResults = userToolResults?.results ?? [];
        commandUuid = null;
        continue;
      }

      // Terminal — no tool_request. End the turn.
      break;
    }
  } catch (err) {
    if (err?.name === "AbortError") {
      stopReason = "cancelled";
    } else {
      dispatch({
        type: A.TURN_ERROR,
        payload: { message: err instanceof Error ? err.message : String(err) },
      });
      throw err;
    }
  } finally {
    dispatch({ type: A.TURN_DONE });
  }

  // /clear refetch lives outside the loop because it's a side effect
  // on the message list, not part of the streaming protocol.
  if (commandUuid === null && refetchMessages?.needed) {
    await refetchMessages.run();
  }

  return { stopReason };
}

// ─── One leg ────────────────────────────────────────────────────────────────
//
// Drives a single POST /turn → SSE iteration. Returns:
//
//   - toolRequest:   the envelope yielded by the backend before
//                    Terminal(tool_request), or null on natural end.
//   - assistantMessage / fullText / etc.: meta for the persisted
//                    assistant bubble.
//   - stopReason:    backend's terminal reason ("completed" / etc).

async function runLeg({
  dispatch,
  conversationId,
  projectId,
  userInput,
  toolResults,
  commandUuid,
  agentStateOverride,
  getToken,
  signal,
  thinking,
  webSearch,
  onSlideEvent,
  onDeckExportReady,
  onDeckExportDomReady,
}) {
  const legResult = {
    fullText: "",
    thinkingText: "",
    searches: [],
    toolNames: [],
    blocks: [],
    usage: null,
    stopReason: "",
    aborted: false,
    assistantMessage: null,
    toolRequest: null,
  };

  // Local mirror of `stream.blocks` because the persisted assistant
  // message needs the same ordered list the renderer just showed; we
  // can't read from React state here. Each stream-event reducer
  // dispatch is shadowed by a parallel update to this local array via
  // the action handlers below.
  //
  // Approach is intentionally simple: replicate the block-building
  // logic locally rather than reading the dispatched state back. Keeps
  // the loop self-contained and avoids tying it to React render
  // cadence.
  const localBlocks = [];
  const lastLocal = () => (localBlocks.length ? localBlocks[localBlocks.length - 1] : null);
  const appendThinkingLocal = (text) => {
    const last = lastLocal();
    if (last && last.type === "thinking" && last.active) {
      last.text += text;
    } else {
      localBlocks.push({ type: "thinking", text, active: true });
    }
  };
  const appendTextLocal = (text) => {
    const last = lastLocal();
    if (last && last.type === "text") {
      last.text += text;
    } else {
      localBlocks.push({ type: "text", text });
    }
  };
  const sealLocalThinking = () => {
    for (const b of localBlocks) {
      if (b.type === "thinking" && b.active) b.active = false;
    }
  };
  const sealLocalTools = () => {
    for (const b of localBlocks) {
      if (b.type === "tool" && b.active) b.active = false;
    }
  };
  const pushLocalSearch = (query) => {
    sealLocalThinking();
    const id = `s${localBlocks.length}`;
    localBlocks.push({ type: "search", id, query, result: "", active: true });
  };
  const finishLocalSearch = (result) => {
    for (let i = localBlocks.length - 1; i >= 0; i--) {
      if (localBlocks[i].type === "search" && localBlocks[i].active) {
        localBlocks[i].active = false;
        localBlocks[i].result = result;
        return;
      }
    }
  };
  const pushLocalTool = (id, name) => {
    sealLocalThinking();
    localBlocks.push({ type: "tool", id, name, active: true, progress: null });
  };
  const updateLocalTool = (id, patch) => {
    for (const b of localBlocks) {
      if (b.type === "tool" && b.id === id) {
        Object.assign(b, patch);
        return;
      }
    }
  };

  const callbacks = {
    onThinkingDelta: (text) => {
      legResult.thinkingText += text;
      appendThinkingLocal(text);
      dispatch({ type: A.THINKING_DELTA, payload: { text } });
    },
    onSearchStart: (query) => {
      legResult.searches.push({ active: true, query, result: "" });
      pushLocalSearch(query);
      dispatch({ type: A.SEARCH_START, payload: { query } });
    },
    onSearchDone: (result) => {
      if (legResult.searches.length > 0) {
        legResult.searches[legResult.searches.length - 1].active = false;
        legResult.searches[legResult.searches.length - 1].result = result;
        finishLocalSearch(result);
      }
      dispatch({ type: A.SEARCH_DONE, payload: { result } });
    },
    onToolCallStart: ({ name, callId }) => {
      if (name && !legResult.toolNames.includes(name)) {
        legResult.toolNames.push(name);
      }
      pushLocalTool(callId, name);
      dispatch({
        type: A.TOOL_CALL_START,
        payload: { id: callId, name },
      });
    },
    onToolCallDone: ({ callId, name, arguments: args }) => {
      // ``tool_call_done`` is the model-SDK signal that the
      // tool_use block has been fully emitted. The tool itself
      // doesn't start running until the assistant stream ends, so we
      // do NOT seal the spinner here — that happens when the
      // backend emits ``tool_call_complete`` after the tool
      // actually finishes (see onToolCallComplete below).
      //
      // TodoWrite arguments contain the new todo list — extract and
      // dispatch so the sidebar updates in real time, before the
      // backend persists.
      if (name === "TodoWrite") {
        try {
          const parsed = JSON.parse(args || "{}");
          if (Array.isArray(parsed.todos)) {
            dispatch({
              type: A.TODOS_SET,
              payload: { todos: parsed.todos },
            });
          }
        } catch {
          /* ignore malformed args */
        }
      }
      dispatch({
        type: A.TOOL_CALL_DONE,
        payload: { id: callId, name },
      });
    },
    onToolCallComplete: ({ callId }) => {
      // Backend just yielded ``tool_call_complete`` for this tool —
      // its execution is finished. Seal the local block and the
      // reducer mirror.
      updateLocalTool(callId, { active: false });
      dispatch({
        type: A.TOOL_CALL_COMPLETE,
        payload: { id: callId },
      });
    },
    onToolProgress: (toolUseId, progress) => {
      updateLocalTool(toolUseId, { progress });
      dispatch({
        type: A.TOOL_PROGRESS,
        payload: { id: toolUseId, progress },
      });
    },
    onToolRequest: (req) => {
      // Capture but do NOT dispatch TOOL_REQUEST_SET yet — that's the
      // job of awaitInteractive after the for-await loop closes. This
      // is the same delay-until-stream-ends pattern the old useChat
      // had as a band-aid, only now it's the loop's natural shape
      // rather than a workaround.
      legResult.toolRequest = req;
    },
    onAssistantMessage: (message) => {
      legResult.assistantMessage = message;
    },
    onStateUpdate: (state) => {
      dispatch({ type: A.CLIENT_STATE_PATCH, payload: state });
    },
    onTextDelta: (text) => {
      legResult.fullText += text;
      appendTextLocal(text);
      dispatch({ type: A.TEXT_DELTA, payload: { text } });
    },
    onText: (text) => {
      legResult.fullText = text;
      const last = lastLocal();
      if (last && last.type === "text") {
        last.text = text;
      } else {
        localBlocks.push({ type: "text", text });
      }
      dispatch({ type: A.TEXT_REPLACE, payload: { text } });
    },
    onDone: ({ usage, stopReason }) => {
      legResult.usage = usage;
      legResult.stopReason = stopReason;
      dispatch({
        type: A.STREAM_DONE,
        payload: { usage, stopReason },
      });
      if (usage) {
        dispatch({ type: A.USAGE_ACCUMULATE, payload: { usage } });
      }
    },
    onError: (message) => {
      dispatch({ type: A.ERROR_SET, payload: { message } });
    },
    onSlideEvent: (type, data) => onSlideEvent?.(type, data),
    onDeckExportReady: (data) => {
      onDeckExportReady?.(data);
    },
    onDeckExportDomReady: (data) => {
      onDeckExportDomReady?.(data);
    },
    onCommandLifecycle: (uuid, state) => {
      dispatch({
        type: A.COMMAND_LIFECYCLE_UPDATE,
        payload: { uuid, state },
      });
    },
    onUserMessage: (message) => {
      // Local slash-command stdout. The streamHandler emits two
      // user_message events per /command — an echo of the input and
      // the stdout. The echo is already in messages (optimistic
      // bubble); the stdout arrives wrapped in
      // <local-command-stdout>...</local-command-stdout>.
      if (!message) return;
      const text = extractTextFromContent(message.content);
      const stdoutMatch = /^<local-command-stdout>([\s\S]*)<\/local-command-stdout>$/.exec(text);
      if (!stdoutMatch) return;
      dispatch({
        type: A.USER_MESSAGE_APPEND,
        payload: {
          message: {
            role: "system",
            content: stdoutMatch[1],
            raw: message,
          },
        },
      });
    },
    onCompactBoundary: (boundary) => {
      if (!boundary) return;
      dispatch({
        type: A.COMPACT_BOUNDARY_APPEND,
        payload: { boundary },
      });
    },
    onCompactWarning: (warning) => {
      if (!warning) return;
      dispatch({ type: A.COMPACT_WARNING_SET, payload: { warning } });
    },
  };

  const token = getToken ? await getToken() : null;
  const agentState = agentStateOverride ?? {};

  try {
    for await (const event of streamTurn(
      {
        conversationId,
        projectId,
        agentState,
        userInput,
        toolResults,
        commandUuid,
      },
      {
        thinking,
        webSearch,
        signal,
        token,
      },
    )) {
      handleStreamEvent(event, callbacks);
    }
  } catch (err) {
    if (err?.name === "AbortError") {
      legResult.aborted = true;
      legResult.stopReason = "cancelled";
    } else {
      dispatch({
        type: A.ERROR_SET,
        payload: { message: err instanceof Error ? err.message : "Network error" },
      });
      throw err;
    }
  }

  // Final pass on local blocks — match the reducer's STREAM_DONE
  // sealing so the persisted snapshot reflects the same final state.
  sealLocalThinking();
  sealLocalTools();

  legResult.blocks = localBlocks.map((b) => ({ ...b }));
  return legResult;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function buildPersistedAssistantMessage(leg) {
  return {
    role: "assistant",
    content: leg.fullText,
    meta: {
      thinkingText: leg.thinkingText || undefined,
      searches: leg.searches.length
        ? leg.searches.map((s) => ({ query: s.query, result: s.result }))
        : undefined,
      toolNames: leg.toolNames.length ? [...leg.toolNames] : undefined,
      usage: leg.usage || undefined,
      cancelled: leg.aborted || undefined,
      raw: leg.assistantMessage?.content,
      blocks: leg.blocks && leg.blocks.length ? leg.blocks : undefined,
    },
  };
}

function extractTextFromContent(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((b) => b && (b.type === "text" || typeof b === "string"))
    .map((b) => (typeof b === "string" ? b : b.text ?? ""))
    .join("");
}
