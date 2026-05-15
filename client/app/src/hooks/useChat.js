import { useCallback, useEffect, useReducer, useRef } from "react";
import * as api from "../api";
import { rowToUiMessage } from "../agent/messageBuilders.js";
import {
  buildAndDownloadDomPptx,
  buildAndDownloadPptx,
} from "../agent/tools/ExportDeckTool/index.js";
import {
  isSlashCommand,
  findCommand,
  findClientHandler,
} from "../commands/index.js";
import {
  chatReducer,
  compactWarningVisible as selectCompactWarningVisible,
  INITIAL_STATE,
  A,
} from "../agent/chatReducer.js";
import { runTurn } from "../agent/agentLoop.js";

const planModeKey = (convId) => `edwin.plan_mode.${convId}`;

// Reconcile plan mode from localStorage, falling back to scanning recent
// messages for EnterPlanMode/ExitPlanMode tool_use blocks. The last such
// block wins — if the user enter/exited multiple times, the most recent
// transition is authoritative.
function derivePlanMode(convId, serverMessages) {
  const stored = typeof localStorage !== "undefined"
    ? localStorage.getItem(planModeKey(convId))
    : null;
  if (stored === "plan" || stored === "default") return stored;

  let mode = "default";
  for (const m of serverMessages) {
    if (m.role !== "assistant") continue;
    const blocks = Array.isArray(m.content) ? m.content : [];
    for (const b of blocks) {
      if (b?.type !== "tool_use") continue;
      if (b.name === "EnterPlanMode") mode = "plan";
      else if (b.name === "ExitPlanMode") mode = "default";
    }
  }
  return mode;
}

export function useChat(
  getToken,
  conversationId,
  {
    projectId = null,
    onSlideEvent,
    // Auto-create wiring. When the user sends a message without an
    // active conversation, ``send`` will:
    //   1. await ``onCreateConversation("New chat")`` for the new row,
    //   2. call ``onSetActiveConversation(newId)`` to switch the App,
    //   3. kick off backend title generation in parallel,
    //   4. ``onSetConversationTitle(newId, title)`` patches the sidebar
    //      label locally once the LLM has produced something.
    // All three are optional — passing ``null`` for any of them disables
    // auto-create (composer falls back to "No active conversation").
    onCreateConversation = null,
    onSetActiveConversation = null,
    onSetConversationTitle = null,
  } = {},
) {
  const [state, dispatch] = useReducer(chatReducer, INITIAL_STATE);

  // A live ref of state so callbacks invoked deep inside agentLoop can
  // read the LATEST clientState without re-creating closures on every
  // reducer update. The loop reads from ``getAgentState()``; we point
  // it at this ref.
  const stateRef = useRef(state);
  stateRef.current = state;

  // The active turn's AbortController. ``stop`` aborts it; the loop's
  // signal-aborted check stops the while loop cleanly.
  const abortRef = useRef(null);

  // Resolve fn for whichever interactive tool_request the agent loop is
  // currently awaiting. ``submitToolAnswer`` / ``submitPlanAnswer``
  // call this to unblock the loop. Cleared between calls.
  const pendingResolveRef = useRef(null);

  // ID of a conversation we just created in this same call to ``send``
  // (auto-create flow). The load-history useEffect below uses this to
  // skip the GET /messages round-trip — the conversation is empty by
  // construction, and the user's optimistic message is already pushed
  // into ``messages``; a fetch would race and overwrite it. Cleared
  // after one cycle.
  const freshlyCreatedConvIdRef = useRef(null);

  // ── Load history on conversation change ────────────────────────────
  useEffect(() => {
    let cancelled = false;
    if (!conversationId) {
      dispatch({ type: A.CONVERSATION_RESET });
      return () => { cancelled = true; };
    }
    // Auto-create flow: this conversation was just minted in ``send``
    // and the optimistic user-message bubble has already been appended.
    // Skip the history fetch so we don't (a) waste a round-trip on a
    // known-empty row, or (b) race a "messages = []" overwrite against
    // the in-flight stream's progressive updates.
    if (freshlyCreatedConvIdRef.current === conversationId) {
      freshlyCreatedConvIdRef.current = null;
      return () => { cancelled = true; };
    }
    (async () => {
      dispatch({ type: A.HYDRATE_HISTORY_START });
      try {
        const token = getToken ? await getToken() : null;
        const rows = await api.getMessages(token, conversationId);
        if (cancelled) return;
        const ui = rows.map(rowToUiMessage).filter(Boolean);
        const mode = derivePlanMode(conversationId, rows);
        dispatch({
          type: A.HYDRATE_HISTORY_DONE,
          payload: { messages: ui, permission_mode: mode },
        });
      } catch (e) {
        if (!cancelled) {
          dispatch({
            type: A.HYDRATE_HISTORY_ERROR,
            payload: {
              message: e instanceof Error ? e.message : "Failed to load history",
            },
          });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [conversationId, getToken]);

  // ── Persist plan mode to localStorage whenever it changes. ──────────
  useEffect(() => {
    if (!conversationId) return;
    try {
      localStorage.setItem(
        planModeKey(conversationId),
        state.clientState.permission_mode,
      );
    } catch { /* ignore storage quota */ }
  }, [conversationId, state.clientState.permission_mode]);

  // ── Public helpers — small wrappers around dispatch ────────────────

  const clear = useCallback(() => {
    dispatch({ type: A.CLEAR_CONVERSATION });
  }, []);

  const dismissCompactWarning = useCallback(() => {
    dispatch({ type: A.COMPACT_WARNING_DISMISS });
  }, []);

  const stop = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    // If the loop was parked awaiting interactive input, free it too —
    // otherwise the abort wouldn't unstick the user-facing modal.
    if (pendingResolveRef.current) {
      pendingResolveRef.current({ results: [], modeChange: null, aborted: true });
      pendingResolveRef.current = null;
    }
  }, []);

  // Re-pull the conversation's canonical message list from the backend.
  // Called by ``send`` after a successful ``/clear`` (backend truncates DB +
  // Redis; the FE has to reset to whatever the new persisted state is —
  // typically just the /clear input + its "Conversation cleared." stdout).
  // We keep clientState.permission_mode so plan mode survives a clear.
  const refetchMessages = useCallback(async () => {
    if (!conversationId) return;
    dispatch({ type: A.HYDRATE_HISTORY_START });
    try {
      const token = getToken ? await getToken() : null;
      const rows = await api.getMessages(token, conversationId);
      const ui = rows.map(rowToUiMessage).filter(Boolean);
      // MESSAGES_REPLACE itself clears loadingHistory — no follow-up.
      dispatch({ type: A.MESSAGES_REPLACE, payload: { messages: ui } });
    } catch (e) {
      dispatch({
        type: A.HYDRATE_HISTORY_ERROR,
        payload: {
          message: e instanceof Error ? e.message : "Failed to refetch history",
        },
      });
    }
  }, [conversationId, getToken]);

  // ── Interactive tool bridge — agentLoop ↔ user-action handlers ────

  // The loop calls this with the tool_request envelope it captured.
  // We dispatch each interactive call into pendingToolRequest so the
  // matching UI (ExitPlanModeUI / AskUserQuestionUI) renders, then
  // park on a promise that the user-action handler resolves. Stays
  // here (rather than agentLoop.js) because it needs access to the
  // pendingResolveRef.
  const awaitInteractive = useCallback(async (toolRequest) => {
    const queue = [
      ...(toolRequest?.parallel_calls || []),
      ...(toolRequest?.sequential_calls || []),
    ];
    if (queue.length === 0) {
      return { results: [], modeChange: null };
    }

    const collected = [];
    let modeChange = null;

    for (const call of queue) {
      dispatch({ type: A.TOOL_REQUEST_SET, payload: { req: call } });

      // Promise resolved by submitToolAnswer / submitPlanAnswer / stop.
      const answer = await new Promise((resolve) => {
        pendingResolveRef.current = resolve;
      });
      pendingResolveRef.current = null;
      dispatch({ type: A.TOOL_REQUEST_CLEAR });

      if (answer?.aborted) {
        return { results: collected, modeChange, aborted: true };
      }
      if (answer?.result) collected.push(answer.result);
      if (answer?.modeChange) modeChange = answer.modeChange;
    }

    return { results: collected, modeChange };
  }, []);

  // Slash commands' client-execution short-circuit. Kept as a separate
  // path because these never POST /turn — they run locally and either
  // print a system bubble (text result) or chain into a prompt-expansion
  // send (prompt result).
  const runClientSlashCommand = useCallback(
    async (cmdName, cmdArgs, { thinking, webSearch }) => {
      const handler = findClientHandler(cmdName);
      if (!handler) {
        dispatch({
          type: A.ERROR_SET,
          payload: { message: `No client handler registered for /${cmdName}` },
        });
        return null;
      }
      try {
        const mod = await handler.load();
        const token = getToken ? await getToken() : null;
        const context = {
          token,
          backendMessages: stateRef.current.messages.map((m) => ({
            role: m.role,
            content: m.content,
          })),
          model: stateRef.current.clientState.model,
          totalUsage: stateRef.current.totalUsage,
          dispatch: () => {},  // legacy hook, no longer used
          clearMessages: clear,
        };
        const result = await mod.call(cmdArgs, context);
        if (result?.type === "text" && result.value) {
          dispatch({
            type: A.USER_MESSAGE_APPEND,
            payload: {
              message: {
                role: "system",
                content: result.value,
                command: result.command || null,
                data: result.data || null,
              },
            },
          });
          return { type: "text" };
        }
        if (result?.type === "prompt") {
          return { type: "prompt", value: result.value, thinking, webSearch };
        }
        return null;
      } catch (err) {
        dispatch({
          type: A.ERROR_SET,
          payload: { message: err instanceof Error ? err.message : "Command failed" },
        });
        return null;
      }
    },
    [getToken, clear],
  );

  // ── Public API: send a user message ─────────────────────────────────
  const send = useCallback(
    async (text, { thinking = false, webSearch = true } = {}) => {
      // Auto-create on first message — non-slash only.
      let activeConvId = conversationId;
      if (!activeConvId) {
        const isSlashEarly = isSlashCommand(text);
        const canAutoCreate =
          !isSlashEarly &&
          typeof onCreateConversation === "function" &&
          typeof onSetActiveConversation === "function";
        if (!canAutoCreate) {
          dispatch({
            type: A.ERROR_SET,
            payload: { message: "No active conversation" },
          });
          return;
        }
        try {
          const conv = await onCreateConversation("New chat");
          if (!conv?.id) {
            dispatch({
              type: A.ERROR_SET,
              payload: { message: "Failed to create conversation" },
            });
            return;
          }
          activeConvId = conv.id;
          freshlyCreatedConvIdRef.current = activeConvId;
          onSetActiveConversation(activeConvId);
        } catch (e) {
          dispatch({
            type: A.ERROR_SET,
            payload: {
              message: e instanceof Error ? e.message : "Failed to create conversation",
            },
          });
          return;
        }

        // Title generation in parallel — best-effort.
        (async () => {
          try {
            const token = getToken ? await getToken() : null;
            const generated = await api.generateConversationTitle(
              token, activeConvId, text,
            );
            if (generated && typeof onSetConversationTitle === "function") {
              onSetConversationTitle(activeConvId, generated);
            }
          } catch (e) {
            console.warn("Auto-title generation failed:", e);
          }
        })();
      }

      // Slash command dispatch
      const isSlash = isSlashCommand(text);
      let cmdName = null;
      let cmdArgs = "";
      if (isSlash) {
        const trimmed = text.trim();
        const spaceIdx = trimmed.indexOf(" ");
        cmdName = (spaceIdx > 0 ? trimmed.slice(1, spaceIdx) : trimmed.slice(1)).toLowerCase();
        cmdArgs = spaceIdx > 0 ? trimmed.slice(spaceIdx + 1) : "";
      }

      if (cmdName) {
        const cmd = findCommand(cmdName);
        const execution = cmd?.execution ?? (cmd?.type === "prompt" ? "server" : null);

        if (cmd && execution === "client") {
          const result = await runClientSlashCommand(cmdName, cmdArgs, { thinking, webSearch });
          if (result?.type === "prompt") {
            return send(result.value, { thinking, webSearch });
          }
          return;
        }
        // execution === "server" OR unknown — fall through to /turn.
      }

      // Mint a command_uuid for slash commands that hit /turn so the
      // backend's lifecycle events can update the bubble's state.
      const commandUuid = isSlash && typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : null;

      // Optimistic user-message bubble.
      dispatch({
        type: A.USER_MESSAGE_APPEND,
        payload: {
          message: commandUuid
            ? { role: "user", content: text, commandUuid, commandState: "pending" }
            : { role: "user", content: text },
        },
      });

      // Run the turn — the loop handles every leg (initial POST + any
      // continuation after an interactive tool_request).
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await runTurn({
          dispatch,
          conversationId: activeConvId,
          projectId,
          initialInput: {
            userInput: text,
            toolResults: [],
            commandUuid,
          },
          getAgentState: () => stateRef.current.clientState,
          awaitInteractive,
          getToken,
          signal: controller.signal,
          thinking,
          webSearch,
          onSlideEvent,
          onDeckExportReady: handleDeckExportReady,
          onDeckExportDomReady: handleDeckExportDomReady,
        });
      } catch {
        // runTurn already dispatched TURN_ERROR; nothing else to do.
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }

      // /clear truncates BE state; refetch the canonical list so local
      // state matches.
      if (cmdName === "clear") {
        await refetchMessages();
      }
    },
    [
      conversationId, projectId, awaitInteractive, getToken,
      onCreateConversation, onSetActiveConversation, onSetConversationTitle,
      onSlideEvent, runClientSlashCommand, refetchMessages,
    ],
  );

  // ── Public API: interactive tool answer handlers ───────────────────
  //
  // These resolve the promise that ``awaitInteractive`` is parked on,
  // unblocking the loop so it can POST the continuation /turn.

  const submitToolAnswer = useCallback(
    (answers, annotations) => {
      const req = stateRef.current.pendingToolRequest;
      if (!req || !pendingResolveRef.current) return;

      const lines = [];
      for (const [q, a] of Object.entries(answers)) {
        lines.push(`Q: "${q}" = "${a}"`);
        const ann = annotations?.[q];
        if (ann?.preview) lines.push(`  Selected preview: ${ann.preview}`);
        if (ann?.notes) lines.push(`  User notes: ${ann.notes}`);
      }

      pendingResolveRef.current({
        result: {
          call_id: req.tool_use_id,
          name: req.tool_name,
          output: lines.join("\n"),
          success: true,
        },
        modeChange: null,
      });
    },
    [],
  );

  const submitPlanAnswer = useCallback(
    (approved, rejectionReason) => {
      const req = stateRef.current.pendingToolRequest;
      if (!req || req.tool_name !== "ExitPlanMode" || !pendingResolveRef.current) {
        return;
      }

      const output = approved
        ? (
            "User approved your plan. Permission mode is now default — "
            + "you can call slide-write tools.\n\n"
            + "Execute the plan in ONE assistant message: emit every "
            + "CreateSlide call in parallel, each with an explicit "
            + "`position` field. For a fresh deck of N slides, use "
            + "positions 0, 1, …, N-1 in plan order; for appends to an "
            + "existing deck of length L, use L, L+1, …. The agent "
            + "loop runs position-bearing creates concurrently — "
            + "do NOT use `after_slide_id` here (that path is serial).\n\n"
            + "Hard count rule: call CreateSlide exactly ONCE per slide "
            + "listed in your plan markdown — N slides in the plan ⇒ "
            + "exactly N CreateSlide calls total, no more. Your "
            + "TodoWrite items mirror the same slides and are "
            + "tracking-only; do NOT iterate them as a separate set of "
            + "work. After the parallel batch returns, briefly confirm "
            + "completion to the user; do not call CreateSlide again."
          )
        : `User rejected your plan: ${rejectionReason || "no reason given"}. Stay in plan mode and revise.`;

      pendingResolveRef.current({
        result: {
          call_id: req.tool_use_id,
          name: req.tool_name,
          output,
          success: true,
        },
        modeChange: approved ? "default" : null,
      });
    },
    [],
  );

  // ── Pagination: load older messages ────────────────────────────────
  const loadOlder = useCallback(async () => {
    if (!conversationId) return 0;
    try {
      const token = getToken ? await getToken() : null;
      const rows = await api.getMessages(token, conversationId, {
        beforeSequence: stateRef.current.messages.length,
        limit: 50,
      });
      if (!rows.length) return 0;
      const ui = rows.map(rowToUiMessage).filter(Boolean);
      dispatch({ type: A.MESSAGES_PREPEND, payload: { messages: ui } });
      return rows.length;
    } catch (e) {
      dispatch({
        type: A.ERROR_SET,
        payload: {
          message: e instanceof Error ? e.message : "Failed to load older messages",
        },
      });
      return 0;
    }
  }, [conversationId, getToken]);

  // ── Deck-export SSE handlers ───────────────────────────────────────
  //
  // The agent's ExportDeck / ExportDeckDom tools push a synthetic SSE
  // event once they've assembled the spec; we build and download the
  // .pptx in the browser here. Same async/error-surface pattern as
  // the original useChat.

  const handleDeckExportReady = useCallback((data) => {
    (async () => {
      try {
        await buildAndDownloadPptx(data?.deck);
      } catch (e) {
        dispatch({
          type: A.ERROR_SET,
          payload: {
            message: e instanceof Error
              ? `Failed to build .pptx: ${e.message}`
              : "Failed to build .pptx",
          },
        });
      }
    })();
  }, []);

  const handleDeckExportDomReady = useCallback((data) => {
    (async () => {
      try {
        await buildAndDownloadDomPptx({
          slides: data?.slides || [],
          filename: data?.filename || "presentation-dom.pptx",
        });
      } catch (e) {
        dispatch({
          type: A.ERROR_SET,
          payload: {
            message: e instanceof Error
              ? `Failed to build DOM .pptx: ${e.message}`
              : "Failed to build DOM .pptx",
          },
        });
      }
    })();
  }, []);

  // ── Public API surface ─────────────────────────────────────────────

  return {
    messages: state.messages,
    busy: state.busy,
    stream: state.stream,
    error: state.error,
    totalUsage: state.totalUsage,
    pendingToolRequest: state.pendingToolRequest,
    conversationId,
    loadingHistory: state.loadingHistory,
    todos: state.todos,
    agentState: state.clientState,
    compactWarning: state.compactWarning,
    compactWarningVisible: selectCompactWarningVisible(state),
    dismissCompactWarning,
    send,
    stop,
    clear,
    submitToolAnswer,
    submitPlanAnswer,
    loadOlder,
  };
}
