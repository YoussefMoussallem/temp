import { useCallback, useEffect, useState } from "react";
import * as api from "../api";

export function useConversations(getToken, projectId) {
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!projectId) {
      setConversations([]);
      return [];
    }
    setLoading(true);
    setError(null);
    try {
      const token = getToken ? await getToken() : null;
      const list = await api.listConversations(token, projectId);
      setConversations(list);
      return list;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return [];
    } finally {
      setLoading(false);
    }
  }, [getToken, projectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = useCallback(
    async (title = "Untitled") => {
      if (!projectId) return null;
      const token = getToken ? await getToken() : null;
      const conv = await api.createConversation(token, projectId, { title });
      setConversations((prev) => [conv, ...prev]);
      return conv;
    },
    [getToken, projectId],
  );

  const remove = useCallback(
    async (id) => {
      const token = getToken ? await getToken() : null;
      await api.deleteConversation(token, id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
    },
    [getToken],
  );

  // Update one conversation's title locally without re-fetching the
  // list. Used by the auto-title generator after the backend has PATCHed
  // the row — the FE already knows what changed, no need for a list
  // round-trip. Keeps the rest of the row (token totals, last_active_at,
  // etc.) intact even though they're stale by a few ms; the next list
  // refresh reconciles them.
  const setTitle = useCallback((id, title) => {
    if (!id || !title) return;
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title } : c)),
    );
  }, []);

  return { conversations, loading, error, refresh, create, remove, setTitle };
}
