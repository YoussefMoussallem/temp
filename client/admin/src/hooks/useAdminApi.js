import { useState, useEffect, useCallback } from "react";
import { useMsal } from "@azure/msal-react";
import { useAuth } from "frontend-comps";

const TOKEN_SCOPES = ["openid", "profile", "email"];

// ``signOut`` is invoked from the helper when silent acquisition fails
// — that's MSAL's canonical "session is dead" signal (AAD revoked,
// refresh expired, etc.). Flipping auth state lets the watchdog in
// ``App.jsx`` redirect to /login. Caller stays getting ``null`` so the
// in-flight request short-circuits without sending a stale token.
async function getIdToken(instance, accounts, signOut) {
  const account = accounts[0];
  if (!account) return null;
  try {
    const resp = await instance.acquireTokenSilent({ scopes: TOKEN_SCOPES, account });
    return resp.idToken;
  } catch {
    try { signOut?.(); } catch { /* best effort */ }
    return null;
  }
}

// Module-level debounce for 401-driven signOut. A page that mounts
// 3-4 ``useAdminApi`` hooks in parallel will fire all of their
// requests at once; without this, a single revoked-session event
// produces N concurrent signOut calls. 2 s window is plenty — by then
// the watchdog has already navigated us off this screen.
let _last401SignOutAt = 0;
function signOutOn401(status, signOut) {
  if (status !== 401) return;
  const now = Date.now();
  if (now - _last401SignOutAt < 2000) return;
  _last401SignOutAt = now;
  try { signOut?.(); } catch { /* best effort */ }
}

/**
 * Read-only admin GET hook.
 *
 * Re-fetches automatically whenever ``url`` changes. ``refetch`` is
 * exposed so a sibling mutation (delete user, change role, etc.) can
 * invalidate the data without re-mounting the component.
 */
export function useAdminApi(url) {
  const { instance, accounts } = useMsal();
  const { signOut } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    const token = await getIdToken(instance, accounts, signOut);
    const headers = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    try {
      const res = await fetch(url, { headers });
      signOutOn401(res.status, signOut);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (err) {
      setError(err.message ?? "Request failed");
    } finally {
      setLoading(false);
    }
  }, [url, instance, accounts, signOut]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}

/**
 * Mutation helper — call ``mutate(method, url, body?)`` from a click
 * handler. Throws an Error with a useful message on non-2xx so the
 * caller can surface it.
 *
 * Returns ``{ mutate, busy }`` so the UI can disable buttons while a
 * request is in flight. The hook is intentionally request-scoped (no
 * cached data) — the mutating component should call ``refetch()`` from
 * a paired ``useAdminApi`` after a successful mutation.
 */
export function useAdminMutation() {
  const { instance, accounts } = useMsal();
  const { signOut } = useAuth();
  const [busy, setBusy] = useState(false);

  const mutate = useCallback(
    async (method, url, body) => {
      setBusy(true);
      try {
        const token = await getIdToken(instance, accounts, signOut);
        const headers = { "Content-Type": "application/json" };
        if (token) headers.Authorization = `Bearer ${token}`;

        const res = await fetch(url, {
          method,
          headers,
          body: body !== undefined ? JSON.stringify(body) : undefined,
        });
        signOutOn401(res.status, signOut);
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          // FastAPI usually packs the message in {"detail": ...}; try to
          // pull it out so the toast / inline error reads cleanly.
          let detail = text;
          try {
            const parsed = JSON.parse(text);
            if (parsed?.detail) detail = parsed.detail;
          } catch {
            /* leave as raw text */
          }
          throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
        }
        if (res.status === 204) return null;
        try {
          return await res.json();
        } catch {
          return null;
        }
      } finally {
        setBusy(false);
      }
    },
    [instance, accounts, signOut],
  );

  return { mutate, busy };
}
