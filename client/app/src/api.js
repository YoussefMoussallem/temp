import { API_BASE as API, AGENT_BASE as AGENT } from "./constants/api.js";
import { invalidateAuth } from "./auth/invalidation.js";

function authHeaders(token) {
  const h = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

// 401 = server has rejected our credentials. Could be: token expired
// without MSAL noticing, session revoked server-side, user account
// disabled in AAD, etc. Either way, the right action is "drop our
// auth state" — ``invalidateAuth`` calls the registered ``signOut``,
// which flips MSAL state, which the watchdog in App.jsx catches and
// redirects to /login. ``invalidateAuth`` is debounced internally so
// a burst of concurrent 401s doesn't trigger N signOuts.
function maybeInvalidateAuth(res) {
  if (res.status === 401) invalidateAuth();
}

// 403 = "authenticated but not authorized for this resource". Distinct
// from 401: the credentials are good, the *permission* is missing.
// Most common in Edwin: a user opens a project they used to have
// access to but were since removed from (the share dialog "Remove"
// path), or a viewer trying to write. We throw this typed error so
// callers can surface a "you don't have access" UI inline rather than
// the generic "Request failed: HTTP 403" toast.
export class ForbiddenError extends Error {
  constructor(message = "You don't have access to this resource.") {
    super(message);
    this.name = "ForbiddenError";
    this.status = 403;
  }
}

// Small helper so callers can do ``catch (e) { if (isForbidden(e)) {...} }``
// without coupling to the class identity (handy across hot-reload
// boundaries where ``instanceof`` can flake).
export function isForbidden(err) {
  return err?.name === "ForbiddenError" || err?.status === 403;
}

// 5xx = "the server failed for transient reasons". Distinct from 4xx
// in that the *request* is fine — backend timeout, db blip, gateway
// error, deploy roll. Worth surfacing as a "something went wrong,
// retry" banner instead of the generic error toast, because the user
// can usually fix it by waiting a few seconds and trying again.
export class ServerError extends Error {
  constructor(message = "The server is having trouble. Please try again.", status = 500) {
    super(message);
    this.name = "ServerError";
    this.status = status;
  }
}

// Network failure (offline, CORS reject, DNS, fetch abort that wasn't
// user-initiated). Surfaced separately because the message we want to
// show is different ("you appear to be offline") and the retry advice
// is different too.
export class NetworkError extends Error {
  constructor(message = "Couldn't reach the server. Check your connection.") {
    super(message);
    this.name = "NetworkError";
  }
}

export function isServerError(err) {
  return err?.name === "ServerError" || (typeof err?.status === "number" && err.status >= 500);
}

export function isNetworkError(err) {
  return err?.name === "NetworkError";
}

// Pub/sub for transient errors. Hooks/utilities that catch a
// ``ServerError`` / ``NetworkError`` push it here; ``ErrorBanner`` in
// App.jsx subscribes and renders the latest one. Keeps the banner
// decoupled from any specific call site, and lets us roll up bursts
// (5 simultaneous 503s = one banner, not five).
const _transientErrorListeners = new Set();

export function subscribeTransientError(listener) {
  _transientErrorListeners.add(listener);
  return () => _transientErrorListeners.delete(listener);
}

export function reportTransientError(err) {
  for (const l of _transientErrorListeners) {
    try { l(err); } catch { /* swallow */ }
  }
}

async function checked(res) {
  maybeInvalidateAuth(res);
  if (res.status === 403) {
    const text = await res.text().catch(() => "");
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      if (parsed?.detail) detail = parsed.detail;
    } catch { /* leave as raw */ }
    throw new ForbiddenError(detail || "You don't have access to this resource.");
  }
  if (res.status >= 500) {
    const text = await res.text().catch(() => "");
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      if (parsed?.detail) detail = parsed.detail;
    } catch { /* leave as raw */ }
    const err = new ServerError(
      detail || `Server error (${res.status}). Please try again.`,
      res.status,
    );
    reportTransientError(err);
    throw err;
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ""}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// Wrap a ``fetch`` call so a thrown TypeError ("Failed to fetch") gets
// classified as a NetworkError and surfaced via the transient-error
// channel. Other thrown errors pass through unchanged.
//
// ``silent: true`` skips the banner — for background fire-and-forget
// calls (registry prime, models list on boot) where a transient
// failure during startup shouldn't terrify the user with a "you
// appear to be offline" toast.
async function netFetch(url, options, { silent = false } = {}) {
  try {
    return await fetch(url, options);
  } catch (err) {
    // ``fetch`` rejects with a TypeError on network failure (offline,
    // CORS, DNS). Anything else (AbortError from an explicit signal,
    // for instance) we pass through — it's not a "show a banner"
    // situation.
    if (err?.name === "AbortError") throw err;
    const wrapped = new NetworkError();
    if (!silent) reportTransientError(wrapped);
    throw wrapped;
  }
}

export async function fetchModels(token) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await netFetch(`${AGENT}/models`, { headers }, { silent: true });
  maybeInvalidateAuth(res);
  return res.json();
}

/**
 * Canonical slash-command registry from the backend.
 *
 * Returns an array of `{name, description, aliases, argument_hint, type,
 * execution, is_hidden}`. `execution` is "server" for backend-run commands
 * (frontend sends via /turn with a command_uuid) or "client" (frontend
 * looks up a local handler by name).
 */
export async function listCommands(token) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await netFetch(`${AGENT}/commands`, { headers }, { silent: true });
  maybeInvalidateAuth(res);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Projects ───────────────────────────────────────────────────────────

export async function listProjects(token) {
  const res = await netFetch(`${API}/projects`, { headers: authHeaders(token) });
  const body = await checked(res);
  return body?.projects || [];
}

export async function createProject(token, { name, description = null }) {
  const res = await netFetch(`${API}/projects`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ name, description }),
  });
  return checked(res);
}

export async function renameProject(token, id, { name, description } = {}) {
  const res = await netFetch(`${API}/projects/${id}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ name, description }),
  });
  return checked(res);
}

export async function deleteProject(token, id) {
  const res = await netFetch(`${API}/projects/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  return checked(res);
}

// ── Project members ────────────────────────────────────────────────────
//
// Sharing: list / add / change role / remove. The backend forwards each
// call to the DB service which enforces the role check (owner-only for
// add / role-change; owner-or-self for remove).

export async function listProjectMembers(token, projectId) {
  const res = await netFetch(`${API}/projects/${projectId}/members`, {
    headers: authHeaders(token),
  });
  const body = await checked(res);
  return body?.members || [];
}

export async function addProjectMember(token, projectId, { email, role = "viewer" }) {
  const res = await netFetch(`${API}/projects/${projectId}/members`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ email, role }),
  });
  return checked(res);
}

export async function updateProjectMemberRole(token, projectId, userId, { role }) {
  const res = await netFetch(`${API}/projects/${projectId}/members/${userId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ role }),
  });
  return checked(res);
}

export async function removeProjectMember(token, projectId, userId) {
  const res = await netFetch(`${API}/projects/${projectId}/members/${userId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  return checked(res);
}

// ── Conversations ──────────────────────────────────────────────────────

export async function listConversations(token, projectId) {
  const res = await netFetch(`${API}/projects/${projectId}/conversations`, {
    headers: authHeaders(token),
  });
  const body = await checked(res);
  return body?.conversations || [];
}

export async function createConversation(token, projectId, { title = "Untitled" } = {}) {
  const res = await netFetch(`${API}/projects/${projectId}/conversations`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ title }),
  });
  return checked(res);
}

export async function updateConversation(token, id, { title } = {}) {
  const res = await netFetch(`${API}/conversations/${id}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ title }),
  });
  return checked(res);
}

export async function deleteConversation(token, id) {
  const res = await netFetch(`${API}/conversations/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  return checked(res);
}

// Best-effort: backend returns ``{title: string|null}`` and the FE
// treats null as "leave the placeholder in place". Failures here must
// never crash the chat (title generation is a UX nicety, not on the
// critical path), so callers swallow exceptions and log only.
export async function generateConversationTitle(token, conversationId, prompt) {
  const res = await netFetch(
    `${AGENT}/conversations/${conversationId}/generate-title`,
    {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ prompt }),
    },
  );
  const body = await checked(res);
  return body?.title || null;
}

// ── Messages ───────────────────────────────────────────────────────────

export async function getMessages(token, conversationId, { beforeSequence = null, limit = 50 } = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (beforeSequence !== null && beforeSequence !== undefined) {
    params.set("before_sequence", String(beforeSequence));
  }
  const res = await netFetch(
    `${API}/conversations/${conversationId}/messages?${params}`,
    { headers: authHeaders(token) },
  );
  const body = await checked(res);
  return body?.messages || [];
}

// ── Slides ─────────────────────────────────────────────────────────────

export async function listSlides(token, projectId) {
  const res = await netFetch(`${API}/projects/${projectId}/slides`, {
    headers: authHeaders(token),
  });
  const body = await checked(res);
  return body?.slides || [];
}

export async function createSlide(token, projectId, { html, title = null, afterSlideId = null } = {}) {
  const res = await netFetch(`${API}/projects/${projectId}/slides`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ html, title, after_slide_id: afterSlideId }),
  });
  return checked(res);
}

export async function updateSlide(token, slideId, { html, title } = {}) {
  const res = await netFetch(`${API}/slides/${slideId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify({ html, title }),
  });
  return checked(res);
}

export async function deleteSlide(token, slideId) {
  const res = await netFetch(`${API}/slides/${slideId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  // Backend renumbers the remaining slides inside the delete transaction
  // and returns the new ordered list (same shape as `reorderSlide`).
  // Callers use it to dispatch SLIDES_REPLACED on the deck reducer.
  const body = await checked(res);
  return body?.slides || [];
}

export async function reorderSlide(token, slideId, { afterSlideId = null } = {}) {
  const res = await netFetch(`${API}/slides/${slideId}/reorder`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ after_slide_id: afterSlideId }),
  });
  const body = await checked(res);
  return body?.slides || [];
}

// ── Memories ───────────────────────────────────────────────────────────
// Two scopes mirror the backend: user-scope memories follow the user
// across all conversations; project-scope memories are tied to one
// project and inherit its access model. The shape returned is the full
// row including body — the FE drawer renders bodies inline, so unlike
// the agent's tool-gated lazy-read pattern we just fetch them all.

export async function listUserMemories(token, azureOid) {
  const res = await netFetch(`${API}/users/${azureOid}/memories`, {
    headers: authHeaders(token),
  });
  const body = await checked(res);
  return body?.memories || [];
}

export async function upsertUserMemory(token, azureOid, payload) {
  const res = await netFetch(`${API}/users/${azureOid}/memories`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  return checked(res);
}

export async function deleteUserMemory(token, azureOid, slug) {
  const res = await netFetch(`${API}/users/${azureOid}/memories/${slug}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok && res.status !== 204) {
    throw new Error(`HTTP ${res.status}`);
  }
}

export async function listProjectMemories(token, projectId) {
  const res = await netFetch(`${API}/projects/${projectId}/memories`, {
    headers: authHeaders(token),
  });
  const body = await checked(res);
  return body?.memories || [];
}

export async function upsertProjectMemory(token, projectId, payload) {
  const res = await netFetch(`${API}/projects/${projectId}/memories`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  return checked(res);
}

export async function deleteProjectMemory(token, projectId, slug) {
  const res = await netFetch(`${API}/projects/${projectId}/memories/${slug}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok && res.status !== 204) {
    throw new Error(`HTTP ${res.status}`);
  }
}

/**
 * AI-driven memory create/edit.
 *
 * User types natural-language input; backend calls an LLM to structure
 * it into the slug / type / name / description / body schema, then
 * upserts. Returns the saved memory in the same shape as the list
 * endpoints so the caller can splice it into local state without a
 * refetch.
 *
 * For scope=user, project_id is ignored (caller's own oid is used).
 * For scope=project, project_id is required.
 *
 * Pass ``slug`` to edit a specific existing entry — the LLM's slug
 * choice is overridden so the upsert overwrites in place. Omit
 * ``slug`` for create (LLM picks one, possibly reusing an existing
 * one if the text supersedes).
 */
export async function saveMemoryFromText(
  token,
  { scope, text, projectId = null, slug = null },
) {
  const res = await netFetch(`${AGENT}/memories/from-text`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      scope,
      text,
      project_id: scope === "project" ? projectId : null,
      slug,
    }),
  });
  return checked(res);
}

