// SSE readers for the agent's streaming endpoints. Each yields
// {event, data} for every server-sent event and returns when the stream
// ends. The shared `readSse` helper keeps the wire-format parsing in one
// place — both /turn and /export-deck use the same fastapi SSE shape.

import { AGENT_BASE as AGENT } from "../constants/api.js";
import { invalidateAuth } from "../auth/invalidation.js";
import { reportTransientError, ServerError, NetworkError } from "../api.js";

async function* readSse(response) {
  // SSE endpoints can also 401 (the rate-limit middleware on the
  // backend short-circuits before the streaming body starts). Same
  // contract as ``api.js`` — invalidate auth state, the watchdog
  // redirects.
  if (response.status === 401) invalidateAuth();
  if (response.status >= 500) {
    const err = new ServerError(
      `Server error (${response.status}). Please try again.`,
      response.status,
    );
    reportTransientError(err);
    throw err;
  }
  if (!response.ok || !response.body) {
    throw new Error(`HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const payload = line.slice(6).trim();
          if (payload === "[DONE]") return;
          try {
            yield { event: currentEvent, data: JSON.parse(payload) };
          } catch { /* skip malformed lines */ }
          currentEvent = "";
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// Model selection (main / search / export) is admin-managed on the
// backend now — see the Models page in the admin app and
// ``app_settings_client`` in the backend. The frontend no longer
// chooses or forwards a model.
export async function* streamTurn(
  { conversationId, projectId = null, agentState = {}, userInput = null, toolResults = [], commandUuid = null },
  { thinking = false, webSearch = true, signal, token } = {},
) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${AGENT}/turn`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        conversation_id: conversationId,
        project_id: projectId || undefined,
        thinking: !!thinking,
        web_search: !!webSearch,
        agent_state: agentState,
        user_input: userInput || undefined,
        tool_results: toolResults,
        command_uuid: commandUuid || undefined,
      }),
      signal,
    });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    const wrapped = new NetworkError();
    reportTransientError(wrapped);
    throw wrapped;
  }

  yield* readSse(res);
}

// SSE reader for POST /api/agent/export-deck. Same conversion pipeline as
// the ExportDeck agent tool, but driven by a UI button (no chat round-
// trip). The conversion model is admin-managed (see the Models page
// in the admin app); the backend reads it from app_settings on every
// request, so the frontend doesn't pass one. Backend yields:
//   - {event: "progress", data: {message, current, total}}
//   - {event: "deck_export_ready", data: {filename, slide_count, deck}}
//   - {event: "error", data: {message}}
//   - {event: "done", data: {}}
export async function* streamExportDeck(
  { projectId, filename = null },
  { signal, token } = {},
) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${AGENT}/export-deck`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        project_id: projectId,
        filename: filename || undefined,
      }),
      signal,
    });
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    const wrapped = new NetworkError();
    reportTransientError(wrapped);
    throw wrapped;
  }

  yield* readSse(res);
}
