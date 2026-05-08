import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";
import { streamTurn } from "../agent/client.js";
import { handleStreamEvent } from "../agent/streamHandler.js";
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

const INITIAL_STREAM = {
  thinkingText: "",
  searches: [],
  toolCalls: [],
  fullText: "",
  usage: null,
  stopReason: "",
  // Ordered blocks for arrival-order rendering. Each entry is
  // { type: "thinking"|"search"|"tool"|"text", ...payload }. The
  // legacy fields above are kept for backward-compat / final assistant
  // meta but the chat UI now reads from ``blocks``. See MessageBlocks
  // for the renderer.
  blocks: [],
};

const INITIAL_CLIENT_STATE = {
  model: "",
  iteration: 0,
  extra: {},
  permission_mode: "default",
};

const INITIAL_TOTAL_USAGE = { inputTokens: 0, outputTokens: 0, requests: 0 };

const planModeKey = (convId) => `edwin.plan_mode.${convId}`;

const LOCAL_STDOUT_RE = /^<local-command-stdout>([\s\S]*)<\/local-command-stdout>$/;

// Concat the .text fields of an Anthropic-style content-block list.
// The backend's user_message SSE event always carries content as
// `[{type:"text", text:"..."}]` (loop shape — sent on as-is to the model),
// but the UI renders a single string. Mirrors the helper in messageBuilders.js.
function extractTextFromContent(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((b) => b && (b.type === "text" || typeof b === "string"))
    .map((b) => (typeof b === "string" ? b : b.text ?? ""))
    .join("");
}

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
  const [messages, setMessages] = useState([]);
  const [clientState, setClientState] = useState(INITIAL_CLIENT_STATE);
  const [busy, setBusy] = useState(false);
  const [stream, setStream] = useState(INITIAL_STREAM);
  const [error, setError] = useState(null);
  const [totalUsage, setTotalUsage] = useState(INITIAL_TOTAL_USAGE);
  const [pendingToolRequest, setPendingToolRequest] = useState(null);
  const [todos, setTodos] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  // Phase 3.6 — compaction surface state.
  //
  // ``compactWarning``     latest WarningState received via SSE
  //                        compact_warning event. null = none seen yet.
  // ``warningDismissedAt`` fill_pct at which the user clicked × on the
  //                        banner. The banner re-arms when the next
  //                        warning's fill_pct exceeds this — matches
  //                        source's "re-shown on next threshold cross"
  //                        requirement. Null means "never dismissed".
  const [compactWarning, setCompactWarning] = useState(null);
  const [warningDismissedAt, setWarningDismissedAt] = useState(null);

  const abortRef = useRef(null);
  const turnContextRef = useRef(null);
  // Active interactive-tool batch. Holds the pending queue, the results
  // collected so far, and any prior tool_results from the backend so the
  // whole batch is submitted atomically when the last call is answered.
  const toolBatchRef = useRef(null);
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
      setMessages([]);
      setClientState(INITIAL_CLIENT_STATE);
      setStream(INITIAL_STREAM);
      setError(null);
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
      setLoadingHistory(true);
      setError(null);
      try {
        const token = getToken ? await getToken() : null;
        const rows = await api.getMessages(token, conversationId);
        if (cancelled) return;
        const ui = rows.map(rowToUiMessage).filter(Boolean);
        setMessages(ui);
        const mode = derivePlanMode(conversationId, rows);
        setClientState({ ...INITIAL_CLIENT_STATE, permission_mode: mode });
        setStream(INITIAL_STREAM);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load history");
        }
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    })();
    return () => { cancelled = true; };
  }, [conversationId, getToken]);

  // ── Persist plan mode to localStorage whenever it changes. ──────────
  useEffect(() => {
    if (!conversationId) return;
    try {
      localStorage.setItem(planModeKey(conversationId), clientState.permission_mode);
    } catch { /* ignore storage quota */ }
  }, [conversationId, clientState.permission_mode]);

  const clear = useCallback(() => {
    setMessages([]);
    setClientState(INITIAL_CLIENT_STATE);
    setStream(INITIAL_STREAM);
    setError(null);
    setTotalUsage(INITIAL_TOTAL_USAGE);
    setTodos([]);
    // Reset the warning surface — emptying the conversation drops
    // token count to ~0; subsequent turns recompute fresh state.
    setCompactWarning(null);
    setWarningDismissedAt(null);
  }, []);

  // Dismiss the warning banner. Records the fill_pct at dismissal
  // time so a future warning that crosses a higher fill level un-
  // dismisses (matches source's "re-shown on next threshold cross").
  const dismissCompactWarning = useCallback(() => {
    const fillAtDismiss = compactWarning?.fill_pct ?? 0;
    setWarningDismissedAt(fillAtDismiss);
  }, [compactWarning]);

  // Computed: should the banner show right now? True when:
  //   1. We have a warning state from the backend, AND
  //   2. The state itself says should_show, AND
  //   3. Either we've never been dismissed, OR the fill_pct has
  //      crossed higher than where we were dismissed (re-arm).
  const compactWarningVisible = !!(
    compactWarning?.should_show &&
    (warningDismissedAt === null
      || (compactWarning.fill_pct ?? 0) > warningDismissedAt)
  );

  // Re-pull the conversation's canonical message list from the backend.
  // Called by `send` after a successful `/clear` (backend truncates DB +
  // Redis; the FE has to reset to whatever the new persisted state is —
  // typically just the /clear input + its "Conversation cleared." stdout).
  // We keep clientState.permission_mode so plan mode survives a clear.
  const refetchMessages = useCallback(async () => {
    if (!conversationId) return;
    setLoadingHistory(true);
    setError(null);
    try {
      const token = getToken ? await getToken() : null;
      const rows = await api.getMessages(token, conversationId);
      const ui = rows.map(rowToUiMessage).filter(Boolean);
      setMessages(ui);
      setStream(INITIAL_STREAM);
      setTotalUsage(INITIAL_TOTAL_USAGE);
      setTodos([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to refetch history");
    } finally {
      setLoadingHistory(false);
    }
  }, [conversationId, getToken]);

  const dispatch = useCallback((action) => {
    // Legacy hook — MESSAGES_REPLACED used to rewrite clientState.messages,
    // which no longer exists. Keeping the dispatch shape for command compat.
    switch (action.type) {
      case "MESSAGES_REPLACED": {
        const newMessages = action.payload.messages || [];
        setMessages(newMessages.map((m) => ({ role: m.role, content: m.content })));
        break;
      }
    }
  }, []);

  const stop = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  // ── Shared stream processor ────────────────────────────────────────
  //
  // All three turn entry points (send, submitToolAnswer, submitPlanAnswer)
  // share the same SSE loop — only the inputs (userInput vs toolResults)
  // and the optimistic UI append differ. This factors out the event
  // switch and returns the accumulated result.
  const processStream = useCallback(
    async ({
      userInput,
      toolResults,
      ctx,
      agentStateOverride,
      commandUuid = null,
      // Auto-create override. When ``send`` has just minted a
      // conversation, the React state hasn't propagated yet, so the
      // closure-captured ``conversationId`` is still ``null``. Callers
      // pass the freshly-created id explicitly here; we fall back to
      // the closure for the steady-state path.
      conversationIdOverride = null,
    }) => {
      const activeConvId = conversationIdOverride || conversationId;
      if (!activeConvId) {
        throw new Error("No active conversation");
      }

      const controller = new AbortController();
      abortRef.current = controller;

      let fullText = "";
      let thinkingText = "";
      const searches = [];
      const toolNames = [];
      let usage = null;
      let stopReason = "";
      let aborted = false;
      let assistantMessage = null;

      // Ordered blocks accumulator. Mutated in place — each callback
      // either (a) appends a new block, or (b) extends the most recent
      // block of the same kind (for streaming text/thinking deltas), or
      // (c) finds a tool/search block by id to flip active/result.
      // ``setStream`` slices it out so React sees a new array ref.
      const blocks = [];
      const lastBlock = () => (blocks.length ? blocks[blocks.length - 1] : null);
      const appendThinking = (text) => {
        const last = lastBlock();
        if (last && last.type === "thinking" && last.active) {
          last.text += text;
        } else {
          blocks.push({ type: "thinking", text, active: true });
        }
      };
      const appendText = (text) => {
        const last = lastBlock();
        if (last && last.type === "text") {
          last.text += text;
        } else {
          blocks.push({ type: "text", text });
        }
      };
      const sealOpenStreaming = () => {
        // Mark any in-flight thinking block as done — the model has
        // moved on to a different block kind, so we shouldn't keep
        // appending thinking deltas to it.
        for (const b of blocks) {
          if (b.type === "thinking" && b.active) b.active = false;
        }
      };
      const pushSearch = (query) => {
        sealOpenStreaming();
        const id = `s${blocks.length}`;
        blocks.push({ type: "search", id, query, result: "", active: true });
        return id;
      };
      const finishLastActiveSearch = (result) => {
        for (let i = blocks.length - 1; i >= 0; i--) {
          if (blocks[i].type === "search" && blocks[i].active) {
            blocks[i].active = false;
            blocks[i].result = result;
            return;
          }
        }
      };
      const pushTool = (id, name) => {
        sealOpenStreaming();
        blocks.push({ type: "tool", id, name, active: true, progress: null });
      };
      const updateTool = (id, patch) => {
        for (const b of blocks) {
          if (b.type === "tool" && b.id === id) {
            Object.assign(b, patch);
            return;
          }
        }
      };
      const snapshotBlocks = () => blocks.map((b) => ({ ...b }));

      const token = getToken ? await getToken() : null;
      const agentState = agentStateOverride || clientState;

      try {
        const callbacks = {
          onThinkingDelta: (text) => {
            thinkingText += text;
            appendThinking(text);
            setStream((s) => ({ ...s, thinkingText, blocks: snapshotBlocks() }));
          },
          onSearchStart: (query) => {
            searches.push({ active: true, query, result: "" });
            pushSearch(query);
            setStream((s) => ({
              ...s,
              searches: [...searches],
              blocks: snapshotBlocks(),
            }));
          },
          onSearchDone: (result) => {
            if (searches.length > 0) {
              searches[searches.length - 1].active = false;
              searches[searches.length - 1].result = result;
              finishLastActiveSearch(result);
              setStream((s) => ({
                ...s,
                searches: [...searches],
                blocks: snapshotBlocks(),
              }));
            }
          },
          onToolCallStart: ({ name, callId }) => {
            if (name && !toolNames.includes(name)) toolNames.push(name);
            pushTool(callId, name);
            setStream((s) => ({
              ...s,
              toolCalls: [
                ...s.toolCalls.map((tc) => ({ ...tc, active: false })),
                { id: callId, name, active: true },
              ],
              blocks: snapshotBlocks(),
            }));
          },
          onToolCallDone: ({ callId, name, arguments: args }) => {
            if (callId) updateTool(callId, { active: false });
            if (name === "TodoWrite") {
              try {
                const todoArgs = JSON.parse(args || "{}");
                if (Array.isArray(todoArgs.todos)) setTodos(todoArgs.todos);
              } catch { /* ignore */ }
            }
            setStream((s) => ({ ...s, blocks: snapshotBlocks() }));
          },
          onToolProgress: (toolUseId, progress) => {
            updateTool(toolUseId, { progress });
            setStream((s) => ({
              ...s,
              toolCalls: s.toolCalls.map((tc) =>
                tc.id === toolUseId ? { ...tc, progress } : tc,
              ),
              blocks: snapshotBlocks(),
            }));
          },
          onToolRequest: (req) => {
            // Phase B envelope: {parallel_calls, sequential_calls,
            // prior_tool_results}. Flatten into a queue — the user
            // answers one modal at a time, and parallel_calls just means
            // no ordering dependency exists. The batch is held in a ref
            // so submitToolAnswer/submitPlanAnswer can walk it.
            const queue = [
              ...(req.parallel_calls || []),
              ...(req.sequential_calls || []),
            ];
            if (queue.length === 0) return;
            toolBatchRef.current = {
              queue: queue.slice(1),
              collected: [],
              priorResults: req.prior_tool_results || [],
              modeChange: null,
            };
            setPendingToolRequest(queue[0]);
          },
          onAssistantMessage: (message) => { assistantMessage = message; },
          onStateUpdate: (state) => {
            setClientState((prev) => ({ ...prev, ...state }));
          },
          onTextDelta: (text) => {
            fullText += text;
            appendText(text);
            setStream((s) => ({ ...s, fullText, blocks: snapshotBlocks() }));
          },
          onText: (text) => {
            fullText = text;
            // Replace the trailing text block (or push a new one).
            // ``onText`` is a full snapshot — used by some events that
            // emit whole-text rather than deltas. We only ever want
            // one trailing text block reflecting the latest snapshot.
            const last = lastBlock();
            if (last && last.type === "text") {
              last.text = text;
            } else {
              blocks.push({ type: "text", text });
            }
            setStream((s) => ({ ...s, fullText, blocks: snapshotBlocks() }));
          },
          onDone: ({ usage: u, stopReason: sr }) => {
            usage = u;
            stopReason = sr;
            setStream((s) => ({ ...s, usage, stopReason }));
            if (u) {
              setTotalUsage((prev) => ({
                inputTokens: prev.inputTokens + (u.input_tokens || 0),
                outputTokens: prev.outputTokens + (u.output_tokens || 0),
                requests: prev.requests + 1,
              }));
            }
          },
          onError: (message) => setError(message),
          onSlideEvent: (type, data) => onSlideEvent?.(type, data),
          onDeckExportReady: (data) => {
            // Backend converted every slide → pptxgenjs spec and shipped
            // the deck spec on this event. Build and trigger download in
            // the browser. Run async (don't block the SSE loop) and
            // surface failures via setError — pptxgenjs.writeFile uses a
            // synthetic <a> click which most browsers permit because the
            // turn was triggered by the user's message a few seconds ago.
            (async () => {
              try {
                await buildAndDownloadPptx(data?.deck);
              } catch (e) {
                setError(
                  e instanceof Error
                    ? `Failed to build .pptx: ${e.message}`
                    : "Failed to build .pptx",
                );
              }
            })();
          },
          onDeckExportDomReady: (data) => {
            // ExportDeckDom backend tool shipped raw slide HTML on this
            // event. Mount each slide off-screen and run the DOM-driven
            // pptx exporter against the live DOM (no per-slide LLM
            // conversion). Same async / error-surface pattern as the
            // LLM-converter path above.
            (async () => {
              try {
                await buildAndDownloadDomPptx({
                  slides: data?.slides || [],
                  filename: data?.filename || "presentation-dom.pptx",
                });
              } catch (e) {
                setError(
                  e instanceof Error
                    ? `Failed to build DOM .pptx: ${e.message}`
                    : "Failed to build DOM .pptx",
                );
              }
            })();
          },
          onCommandLifecycle: (uuid, state) => {
            // Update the optimistic user-command bubble with started/completed.
            // Keyed on command_uuid attached to the bubble at send-time.
            setMessages((prev) => prev.map((m) =>
              m.commandUuid === uuid
                ? { ...m, commandState: state }
                : m,
            ));
          },
          onUserMessage: (message) => {
            // Local-command short-circuit: backend streams two user_message
            // events — (1) an echo of the raw slash input, then (2) the
            // command's stdout wrapped in <local-command-stdout>...</local-command-stdout>.
            // We drop (1) because the optimistic command bubble already
            // shows the user's typed input, and we strip the wrapper from
            // (2) before storing as plain text for the markdown renderer.
            if (!message) return;
            const text = extractTextFromContent(message.content);
            const stdoutMatch = LOCAL_STDOUT_RE.exec(text);
            if (!stdoutMatch) return;
            setMessages((prev) => [
              ...prev,
              { role: "system", content: stdoutMatch[1], raw: message },
            ]);
          },
          onCompactBoundary: (boundary) => {
            // Inject inline as a special-role message between the user's
            // input and the assistant's response. The backend ALSO
            // persists the same boundary as a system-role row (see
            // utils/compact_boundary_marker.py), so on the next
            // refetch / hard reload the divider re-appears via
            // rowToUiMessage. Inserting it optimistically here means
            // the user sees the divider immediately without waiting
            // for a refetch round-trip.
            if (!boundary) return;
            setMessages((prev) => [
              ...prev,
              { role: "compact-boundary", boundary },
            ]);
          },
          onCompactWarning: (warning) => {
            // Update the latest warning state. The banner's visibility
            // is computed from this + warningDismissedAt — see
            // ``compactWarningVisible`` above.
            if (!warning) return;
            setCompactWarning(warning);
            // If this warning's fill_pct is *higher* than where the user
            // last dismissed, re-arm the dismissal so the banner shows.
            // Lower or equal fill stays dismissed — only crossing higher
            // re-shows it.
            setWarningDismissedAt((prev) =>
              prev !== null && (warning.fill_pct ?? 0) > prev ? null : prev,
            );
          },
        };

        for await (const event of streamTurn(
          { conversationId: activeConvId, projectId, agentState, userInput, toolResults, commandUuid },
          {
            thinking: ctx.thinking,
            webSearch: ctx.webSearch,
            signal: controller.signal,
            token,
          },
        )) {
          handleStreamEvent(event, callbacks);
        }
      } catch (err) {
        if (err.name === "AbortError") {
          aborted = true;
          stopReason = "cancelled";
        } else {
          setError(err instanceof Error ? err.message : "Network error");
        }
      }

      abortRef.current = null;

      // Final pass: any thinking block still flagged active (model
      // ended without emitting a non-thinking block after it) gets
      // sealed so the persisted view doesn't show a "still thinking"
      // spinner forever.
      sealOpenStreaming();

      return {
        fullText,
        thinkingText,
        searches,
        toolNames,
        usage,
        stopReason,
        aborted,
        assistantMessage,
        blocks: snapshotBlocks(),
      };
    },
    [conversationId, projectId, clientState, getToken, onSlideEvent],
  );

  // Append the assistant UI bubble after a stream finishes.
  const appendAssistantToUi = useCallback(
    ({ fullText, assistantMessage, thinkingText, searches, toolNames, usage, aborted, blocks }) => {
      if (!fullText && !assistantMessage) return;
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: fullText,
          meta: {
            thinkingText: thinkingText || undefined,
            searches: searches.length
              ? searches.map((s) => ({ query: s.query, result: s.result }))
              : undefined,
            toolNames: toolNames.length ? [...toolNames] : undefined,
            usage: usage || undefined,
            cancelled: aborted || undefined,
            raw: assistantMessage?.content,
            // Ordered blocks captured at stream-end time. Lets the
            // post-stream AssistantMessage render keep the same
            // arrival-order layout the user just saw stream live —
            // no flicker / re-grouping when the spinner hands off
            // to the persisted bubble.
            blocks: blocks && blocks.length ? blocks : undefined,
          },
        },
      ]);
      setClientState((prev) => ({ ...prev, iteration: prev.iteration + 1 }));
    },
    [],
  );

  // ── Public API: send a user message ─────────────────────────────────
  // Model selection (main / search) is admin-managed on the backend;
  // the frontend no longer chooses one. ``thinking`` and ``webSearch``
  // remain per-turn user toggles.
  const send = useCallback(
    async (text, { thinking = false, webSearch = true } = {}) => {
      // Auto-create on first message. When the user has no active
      // conversation but the project + auto-create wiring is present,
      // we mint one ("New chat" placeholder), set it active, fire
      // backend title generation in parallel, and proceed with the
      // send flow against the freshly-created id. We only auto-create
      // for natural-language input — slash commands are advanced
      // controls and should error explicitly if there's no
      // conversation, rather than spawning an empty sidebar entry.
      let activeConvId = conversationId;
      if (!activeConvId) {
        const isSlashEarly = isSlashCommand(text);
        const canAutoCreate =
          !isSlashEarly &&
          typeof onCreateConversation === "function" &&
          typeof onSetActiveConversation === "function";
        if (!canAutoCreate) {
          setError("No active conversation");
          return;
        }
        try {
          const conv = await onCreateConversation("New chat");
          if (!conv?.id) {
            setError("Failed to create conversation");
            return;
          }
          activeConvId = conv.id;
          // Mark this id so the load-history useEffect skips its
          // GET /messages round-trip when conversationId catches up.
          freshlyCreatedConvIdRef.current = activeConvId;
          onSetActiveConversation(activeConvId);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Failed to create conversation");
          return;
        }

        // Title generation in parallel. Doesn't block sending — the
        // chat works fine with the placeholder; the title catches up
        // a few seconds later. Failures swallowed (best-effort).
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

      // Slash command dispatch. Backend is the canonical registry.
      //   - execution: "server" → send raw /cmd to backend via /turn with a
      //     command_uuid; backend expands prompt-type commands and runs
      //     local-type ones itself. Falls through to normal send below.
      //   - execution: "client" → look up the local handler by name and
      //     run it client-side (no /turn call).
      //
      // cmdName is hoisted so post-send hooks (e.g. /clear refetch) can
      // branch on it without re-parsing the input string.
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
          const handler = findClientHandler(cmdName);
          if (handler) {
            setBusy(true);
            setError(null);
            try {
              const mod = await handler.load();
              const token = getToken ? await getToken() : null;
              const context = {
                token,
                backendMessages: messages.map((m) => ({ role: m.role, content: m.content })),
                model: clientState.model,
                totalUsage,
                dispatch,
                clearMessages: clear,
              };
              const result = await mod.call(cmdArgs, context);
              if (result?.type === "text" && result.value) {
                setMessages((prev) => [
                  ...prev,
                  {
                    role: "system",
                    content: result.value,
                    command: result.command || null,
                    data: result.data || null,
                  },
                ]);
              } else if (result?.type === "prompt") {
                setBusy(false);
                return send(result.value, { thinking, webSearch });
              }
            } catch (err) {
              setError(err instanceof Error ? err.message : "Command failed");
            }
            setBusy(false);
            return;
          }
          // No client handler found for a client-execution command.
          setError(`No client handler registered for /${cmdName}`);
          return;
        }

        // execution === "server" OR unknown command → fall through to /turn.
        // The existing slash-fallthrough logic below attaches command_uuid.
      }

      // Normal message flow. Slash commands that fell through the client
      // registry reach the backend — mint a uuid so the lifecycle listener
      // can update the bubble as started/completed.
      const commandUuid = isSlash && typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : null;

      setMessages((prev) => [
        ...prev,
        commandUuid
          ? { role: "user", content: text, commandUuid, commandState: "pending" }
          : { role: "user", content: text },
      ]);
      setBusy(true);
      setError(null);
      setStream(INITIAL_STREAM);

      const ctx = { thinking, webSearch };
      turnContextRef.current = ctx;

      const result = await processStream({
        userInput: text,
        toolResults: [],
        ctx,
        commandUuid,
        conversationIdOverride: activeConvId,
      });

      appendAssistantToUi(result);

      // /clear is a backend command that truncates the conversation's
      // messages + Redis cache and resets its token counters. Refetch
      // the canonical list so local state matches the (now cleared)
      // server state — the optimistic /clear bubble + the stdout SSE
      // bubble are replaced by their persisted DB rows.
      if (cmdName === "clear") {
        await refetchMessages();
      }

      setBusy(false);
    },
    [
      conversationId, messages, clientState.model, totalUsage,
      dispatch, clear, processStream, appendAssistantToUi, getToken,
      refetchMessages,
      onCreateConversation, onSetActiveConversation, onSetConversationTitle,
    ],
  );

  // ── Batch finalization ─────────────────────────────────────────────
  // Called by submitToolAnswer/submitPlanAnswer after each call's result
  // is captured. If more calls remain in the batch, show the next modal;
  // otherwise submit the full tool_results list to /turn in one round-trip.
  const advanceBatch = useCallback(
    async (callResult, { modeChange } = {}) => {
      const batch = toolBatchRef.current;
      if (!batch) return;
      batch.collected.push(callResult);
      if (modeChange) batch.modeChange = modeChange;

      if (batch.queue.length > 0) {
        const [next, ...rest] = batch.queue;
        batch.queue = rest;
        setPendingToolRequest(next);
        return;
      }

      const ctx = turnContextRef.current;
      if (!ctx) return;

      const toolResults = [
        ...batch.priorResults.map((r) => ({
          call_id: r.call_id,
          name: "",
          output: r.output,
          success: r.success,
        })),
        ...batch.collected,
      ];

      let agentStateOverride;
      if (batch.modeChange === "default") {
        agentStateOverride = { ...clientState, permission_mode: "default" };
        setClientState(agentStateOverride);
        setTodos([]);
      }

      toolBatchRef.current = null;
      setPendingToolRequest(null);
      setBusy(true);
      setError(null);
      setStream(INITIAL_STREAM);

      const result = await processStream({
        userInput: null,
        toolResults,
        ctx,
        agentStateOverride,
      });

      appendAssistantToUi(result);
      setBusy(false);
    },
    [clientState, processStream, appendAssistantToUi],
  );

  // ── Public API: answer an AskUserQuestion call ─────────────────────
  const submitToolAnswer = useCallback(
    async (answers, annotations) => {
      const req = pendingToolRequest;
      if (!req) return;

      const lines = [];
      for (const [q, a] of Object.entries(answers)) {
        lines.push(`Q: "${q}" = "${a}"`);
        const ann = annotations?.[q];
        if (ann?.preview) lines.push(`  Selected preview: ${ann.preview}`);
        if (ann?.notes) lines.push(`  User notes: ${ann.notes}`);
      }

      await advanceBatch({
        call_id: req.tool_use_id,
        name: req.tool_name,
        output: lines.join("\n"),
        success: true,
      });
    },
    [pendingToolRequest, advanceBatch],
  );

  // ── Public API: approve/reject an ExitPlanMode plan ────────────────
  const submitPlanAnswer = useCallback(
    async (approved, rejectionReason) => {
      const req = pendingToolRequest;
      if (!req || req.tool_name !== "ExitPlanMode") return;

      const output = approved
        ? "approved"
        : `rejected: ${rejectionReason || "no reason given"}`;

      await advanceBatch(
        {
          call_id: req.tool_use_id,
          name: req.tool_name,
          output,
          success: true,
        },
        { modeChange: approved ? "default" : undefined },
      );
    },
    [pendingToolRequest, advanceBatch],
  );

  // ── Pagination: load older messages ────────────────────────────────
  const loadOlder = useCallback(async () => {
    if (!conversationId) return 0;
    // Find the smallest sequence we have. We stored `raw`/meta but not seq,
    // so keep a parallel oldest tracker via server round-trip.
    try {
      const token = getToken ? await getToken() : null;
      // Use the oldest currently-loaded message's sequence. Since rowToUi
      // dropped it, we re-query by asking the server for messages before the
      // smallest we don't have — approximated by current messages length.
      const rows = await api.getMessages(token, conversationId, {
        beforeSequence: messages.length,  // works when no gaps; good enough for v1
        limit: 50,
      });
      if (!rows.length) return 0;
      const ui = rows.map(rowToUiMessage).filter(Boolean);
      setMessages((prev) => [...ui, ...prev]);
      return rows.length;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load older messages");
      return 0;
    }
  }, [conversationId, getToken, messages.length]);

  return {
    messages,
    busy,
    stream,
    error,
    totalUsage,
    pendingToolRequest,
    conversationId,
    loadingHistory,
    send,
    stop,
    clear,
    submitToolAnswer,
    submitPlanAnswer,
    loadOlder,
    todos,
    agentState: clientState,
    // Phase 3.6 — compaction surface.
    // ``compactWarning`` is the raw WarningState (or null);
    // ``compactWarningVisible`` is the should-show predicate after
    // dismissal logic; ``dismissCompactWarning`` records the dismissal
    // and re-arms on next threshold cross.
    compactWarning,
    compactWarningVisible,
    dismissCompactWarning,
  };
}
