import { useCallback, useEffect, useState } from "react";
import * as api from "../api";

/**
 * Fetch + mutate long-term memories for one scope.
 *
 * The two scope tables share a shape but live behind different routes
 * + access models, so this hook is parametric on ``scope`` and the
 * relevant id (``azureOid`` for user, ``projectId`` for project).
 * Pass the id as ``null`` to disable — the hook returns an empty
 * list and skips the fetch (useful for the "This project" tab when
 * no project is active).
 *
 * Phase 1's agent surface treats memory as tool-gated (no auto-load)
 * to keep token cost flat; the Phase 3 UI here is the opposite —
 * fetch all rows including bodies because the drawer renders them
 * inline. The two patterns live behind the same endpoints.
 */
export function useMemories(getToken, { scope, scopeId }) {
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!scopeId) {
      setMemories([]);
      setLoading(false);
      setError(null);
      return [];
    }
    setLoading(true);
    setError(null);
    try {
      const token = getToken ? await getToken() : null;
      const list =
        scope === "user"
          ? await api.listUserMemories(token, scopeId)
          : await api.listProjectMemories(token, scopeId);
      setMemories(list);
      return list;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return [];
    } finally {
      setLoading(false);
    }
  }, [getToken, scope, scopeId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const upsert = useCallback(
    async (payload) => {
      if (!scopeId) throw new Error("No scope id");
      const token = getToken ? await getToken() : null;
      const saved =
        scope === "user"
          ? await api.upsertUserMemory(token, scopeId, payload)
          : await api.upsertProjectMemory(token, scopeId, payload);
      // Upsert: replace if slug exists, else prepend (newest first to
      // match the API's ``ORDER BY updated_at DESC``).
      setMemories((prev) => {
        const idx = prev.findIndex((m) => m.slug === saved.slug);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = saved;
          return next;
        }
        return [saved, ...prev];
      });
      return saved;
    },
    [getToken, scope, scopeId],
  );

  // AI-driven create / edit. Sends free-form text; the backend LLM
  // structures it and upserts. Returns the saved row so the caller can
  // immediately render it (no refetch needed).
  const createFromText = useCallback(
    async (text) => {
      if (!scopeId) throw new Error("No scope id");
      const token = getToken ? await getToken() : null;
      const saved = await api.createMemoryFromText(token, {
        scope,
        text,
        projectId: scope === "project" ? scopeId : null,
      });
      setMemories((prev) => {
        const idx = prev.findIndex((m) => m.slug === saved.slug);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = saved;
          return next;
        }
        return [saved, ...prev];
      });
      return saved;
    },
    [getToken, scope, scopeId],
  );

  const remove = useCallback(
    async (slug) => {
      if (!scopeId) throw new Error("No scope id");
      const token = getToken ? await getToken() : null;
      if (scope === "user") {
        await api.deleteUserMemory(token, scopeId, slug);
      } else {
        await api.deleteProjectMemory(token, scopeId, slug);
      }
      setMemories((prev) => prev.filter((m) => m.slug !== slug));
    },
    [getToken, scope, scopeId],
  );

  return { memories, loading, error, refresh, upsert, createFromText, remove };
}
