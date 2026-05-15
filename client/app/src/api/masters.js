// Masters API client.
//
// Lives next to api.js (top-level) for now; if api.js gets carved up
// further by resource we'd colocate the masters helpers there. This
// module is deliberately self-contained — no shared mutable state, no
// auth side-effects. The auth header is the caller's responsibility.

import { API_BASE as API, AGENT_BASE as AGENT } from "../constants/api.js";

function authHeaders(token) {
  const h = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

async function checked(res) {
  if (res.status === 204) return null;
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {
      /* leave raw */
    }
    throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
  }
  // ASGI/test fakes don't always set content-type; default to JSON.
  return res.json();
}

export async function listMasters(token, projectId) {
  // Phase 2.0: response carries both the list AND the project's active
  // master pointer. Returning a tuple-shaped object keeps the hook's
  // single-fetch flow without a second roundtrip and surfaces the
  // active id consistently across page navigations.
  const res = await fetch(`${API}/projects/${projectId}/masters`, {
    headers: authHeaders(token),
  });
  const body = await checked(res);
  return {
    masters: body?.masters || [],
    activeMasterId: body?.active_master_id ?? null,
  };
}

export async function getMaster(token, masterId) {
  const res = await fetch(`${API}/masters/${masterId}`, {
    headers: authHeaders(token),
  });
  return checked(res);
}

// Multipart upload via the agent backend, which extracts the manifest
// from bytes and forwards everything to db-service. The browser sets
// the multipart Content-Type itself once we hand it a FormData — we
// must NOT pass Content-Type explicitly or we'll clobber the boundary.
//
// `fonts` is an optional array of File objects (.ttf / .otf / .woff /
// .woff2) — bundled brand fonts uploaded alongside the .pptx. The
// backend infers family/weight/style from each filename, so the FE
// only needs to forward the files.
export async function uploadMaster(token, projectId, file, name = null, fonts = []) {
  const fd = new FormData();
  fd.append("file", file, file.name);
  fd.append("project_id", projectId);
  if (name) fd.append("name", name);
  for (const font of fonts || []) {
    if (!font) continue;
    fd.append("fonts", font, font.name);
  }

  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${AGENT}/masters/upload`, {
    method: "POST",
    headers,
    body: fd,
  });
  return checked(res);
}

export async function activateMaster(token, masterId) {
  const res = await fetch(`${API}/masters/${masterId}/activate`, {
    method: "POST",
    headers: authHeaders(token),
  });
  return checked(res);
}

export async function deleteMaster(token, masterId) {
  const res = await fetch(`${API}/masters/${masterId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  return checked(res);
}

// Phase 2.4 — curation surface.
//
// Layouts hang off masters; the curation UI reads them once with
// listLayouts and dispatches per-row PATCHes (kind/enabled/notes/
// position) or POST /default as the user edits.

export async function listLayouts(token, masterId) {
  const res = await fetch(`${API}/masters/${masterId}/layouts`, {
    headers: authHeaders(token),
  });
  const body = await checked(res);
  return body?.layouts || [];
}

export async function updateLayout(token, layoutId, patch) {
  // Three-state semantics on the server:
  //   * field omitted (default null/undefined) → leave unchanged
  //   * user_kind="" → clear the override
  //   * notes="__CLEAR__" → clear notes
  // The caller is responsible for using these sentinels when needed.
  const res = await fetch(`${API}/master_layouts/${layoutId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(patch),
  });
  return checked(res);
}

export async function setLayoutDefault(token, layoutId) {
  const res = await fetch(`${API}/master_layouts/${layoutId}/default`, {
    method: "POST",
    headers: authHeaders(token),
  });
  return checked(res);
}
