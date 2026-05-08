import { useCallback } from "react";
import { useMsal } from "@azure/msal-react";
import { useAuth } from "frontend-comps";

const TOKEN_SCOPES = ["openid", "profile", "email"];

export function useToken() {
  const { instance, accounts } = useMsal();
  // We use ``signOut`` from frontend-comps' ``useAuth`` rather than
  // calling ``instance.logoutRedirect`` directly — keeps logout flow
  // owned by frontend-comps so the redirect URI / popup behaviour stays
  // consistent across the app.
  const { signOut } = useAuth();

  const getToken = useCallback(async () => {
    const account = accounts[0];
    if (!account) return null;

    try {
      const response = await instance.acquireTokenSilent({
        scopes: TOKEN_SCOPES,
        account,
      });
      return response.idToken;
    } catch {
      // Silent acquisition failure is the canonical "session is dead"
      // signal in MSAL — usually InteractionRequiredAuthError because
      // AAD revoked the session, refresh-token expired, or the user
      // signed out elsewhere. ``signOut`` flips MSAL state, the auth
      // watchdog in App.jsx then navigates to /login. We also still
      // return null so the caller's API call short-circuits without
      // an Authorization header rather than firing with a stale token.
      try { signOut(); } catch { /* ignore — best effort */ }
      return null;
    }
  }, [instance, accounts, signOut]);

  return getToken;
}

/**
 * The signed-in user's Azure AD object id (the same value the backend
 * stores as ``users.azure_oid``). Used by frontend code that needs to
 * compare "who am I?" against rows returned by the API — e.g. so the
 * share dialog can label the current user's row "(you)" and let them
 * leave the project.
 */
export function useCurrentUserOid() {
  const { accounts } = useMsal();
  return accounts[0]?.localAccountId || null;
}
