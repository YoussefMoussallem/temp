# Chat loop refactor — scope and commit plan

Replace Edwin's `client/app/src/hooks/useChat.js` React-state pattern with a RevitCode-style external `agentLoop.js` orchestrator + reducer. Removes the band-aids (`activeStreamRef`, `deferredToolRequest`) by eliminating the race surface that made them necessary, and prepares the FE for parallel mid-stream tool dispatch, subagents, and richer permission gates later.

## What changes architecturally

| Today (useChat) | After refactor |
|---|---|
| ~10 `useState` calls scattered through the hook | One `useReducer` with a typed `chatReducer` |
| Three entry points (`send`, `advanceBatch`, `submitPlanAnswer`) that each call `processStream` once per FE-initiated leg | One `agentLoop()` async function that owns the whole turn through a `while` loop |
| `activeStreamRef` generation counter band-aid to stop stale `setBusy(false)` from a still-draining prior leg | Loop owns busy/streaming lifecycle; no prior stream can clobber it because there's no second `processStream` race |
| `deferredToolRequest` captured in `onToolRequest` and committed post-for-await to dodge the persistence-race window | Loop handles the leg boundary explicitly — interactive handoff is an `await coordinator.drain()` or `await userAnswer`, no race window |
| Per-leg `POST /turn` initiated from the FE on each user click | Loop chains continuation POSTs in-line; user clicks resolve a promise the loop is awaiting |
| BE-side persistence ordering as-is (post-stream `to_persist` drain) | **Unchanged.** This refactor is FE-only. Persistence ordering is a separate (BE) item if we want to fix the race source at the BE too |

What the refactor does NOT include in this scope:

* Per-message FE-side persistence (RevitCode has `chatPersister.js` — Edwin's BE persists). Skip.
* `FrontendStreamingCoordinator` for mid-stream FE tool dispatch. Edwin has very few FE-side tools (ExportDeck variants run via SSE events already, not as proper FE tools). Defer.
* Subagent dispatch / forked skills / `AgentTool`. Out of scope for this branch — those are separate features that will be easier to land *on top of* this refactor.
* Backend changes. Strictly frontend.

## File-level scope

**New files:**

* `client/app/src/agent/chatReducer.js` — state shape + reducer + action constants
* `client/app/src/agent/agentLoop.js` — the orchestrator function

**Modified files:**

* `client/app/src/hooks/useChat.js` — refactored to wrap the reducer and dispatch to `agentLoop`; old `send` / `advanceBatch` / `submitToolAnswer` / `submitPlanAnswer` become thin shims that resolve a promise the loop is awaiting

**Untouched files (FE):**

* `client/app/src/agent/client.js` — SSE reader stays the same
* `client/app/src/agent/streamHandler.js` — event dispatcher stays the same (the dispatch target changes from callbacks to reducer actions)
* `client/app/src/agent/messageBuilders.js` — message hydration stays the same
* All `client/app/src/components/**` — consume `chat` from context exactly as today; the shape returned by `useChat` doesn't change

## Commit plan

Each commit is independently shippable / revertable.

### Commit 1 — Foundation: reducer + loop skeleton (no behavior change)

Add `chatReducer.js` and `agentLoop.js` as new, unused modules.

* `chatReducer.js` exports `INITIAL_STATE`, `reducer`, and named action types. Pure functions, no side effects, no React imports.
* `agentLoop.js` exports `runTurn({ dispatch, ... })` — signature only, implementation stubs throw.
* `useChat.js` untouched. The new files compile and parse but nothing imports them yet.

Goal: get the structure on disk for review.

### Commit 2 — Wire the reducer into useChat (parallel mode)

`useChat.js` adds `useReducer(reducer, INITIAL_STATE)` alongside the existing `useState` calls. Every state setter now ALSO dispatches the matching action — but readers still use the `useState`-backed values. No behavior change; runtime cost is a duplicate update per state change.

This is a safety step: it lets us validate that the reducer's state stays in lock-step with the legacy state through one round of testing. If anything's off, we can compare side-by-side.

### Commit 3 — Switch readers from useState to reducer state

Flip every read site in `useChat.js` from the local `useState` value to the reducer's value. Delete the now-redundant `useState` calls.

After this commit, the reducer is the source of truth. State updates still flow through the legacy callback shape inside `processStream` (which now dispatches actions instead of calling setX).

### Commit 4 — Implement `agentLoop.runTurn`

Replace the body of `processStream` with a call to `agentLoop.runTurn`. The loop owns:

* Opening the SSE stream via `streamTurn`
* Iterating events and dispatching reducer actions through `handleStreamEvent`
* Detecting `tool_request` and awaiting the user's response via a promise stored in state
* Chaining a continuation `/turn` POST after `tool_request` resolves
* Looping until terminal

The hook's exposed `send` / `submitPlanAnswer` / `submitToolAnswer` become thin: they enqueue a user action that the loop is awaiting (via a ref-held resolve fn).

### Commit 5 — Remove band-aids

* Delete `activeStreamRef` and its gates.
* Delete `deferredToolRequest` and the post-for-await processing block. `onToolRequest` now dispatches a reducer action directly; the loop's `while` decides when to await.
* Delete `turnContextRef` (loop carries `ctx` in its closure).
* Delete the `toolBatchRef` queue if it's still around (loop owns the queue).

The diagnostic `[edwin-stream]` console logs can come out here too, since their reason-to-exist (the streaming-stop bug) is being structurally eliminated.

### Commit 6 — Cleanup + verification

* Run through every plan-mode + AskUserQuestion + slash-command flow live.
* Sweep dead imports, unused helpers.
* Update the agent-loop architecture diagram (`agent-loop-architecture.md`) to mark the previously-red items as green.
* Update the project memory file (`memory/project_chat_loop_refactor.md`) to mark the refactor done.

## Risk areas / open questions

* **Conversation switching mid-stream.** Today `useChat.js`'s history-load `useEffect` resets state on `conversationId` change. The loop needs to react to that — likely by aborting any in-flight turn and dispatching `HYDRATE_CHAT`.
* **Auto-create conversation flow.** `send` currently auto-creates a conversation when there's no active one. The loop has to either accept a "create-if-needed" mode or have the caller do the create first. Probably cleaner to lift the create above the loop.
* **Slash-command client-handlers.** `send` short-circuits for client-execution slash commands (no `/turn`). The loop has to either dispatch to those handlers OR they need to bypass the loop entirely. Probably the latter.
* **Compact warning + dismissal.** Stateful, lives outside any turn. Reducer needs `COMPACT_WARNING_SET` and `COMPACT_WARNING_DISMISS` actions.
* **Subagent message channel (`onSubagentMessage`).** Edwin doesn't have subagents yet, so the loop's hook is a no-op for now. Wire it as `() => {}` and leave the seam.

## Estimated effort

Per commit: 30 min – 2 hours of focused work. Total: about a day if nothing surprises us.

## Stopping criteria for this branch

When commits 1–6 land, the band-aids are gone, all current chat flows work (plan approval, Q&A, slash commands, slide tools, image uploads), and the agent-loop diagram is updated. We do NOT need to ship subagents or coordinators on this branch — those go on follow-up branches built on top.
