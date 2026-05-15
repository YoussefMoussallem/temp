// Single-master detail hook for the curation page.
//
// Loads one master row + its layouts. Exposes optimistic per-layout
// PATCH and "mark default" actions; on a backend error we rollback so
// the UI reflects authoritative server state. Activate / delete reuse
// the masters API directly.
//
// Surface mirrors useMasters intentionally — same shape conventions
// (loading, error, refresh) so the screens read alike.

import { useCallback, useEffect, useState } from "react";
import {
  getMaster,
  listMasters,
  listLayouts,
  updateLayout,
  setLayoutDefault,
  activateMaster,
  deleteMaster,
} from "../api/masters.js";

export function useMaster(masterId, getToken) {
  const [master, setMaster] = useState(null);
  const [layouts, setLayouts] = useState([]);
  const [activeMasterId, setActiveMasterId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!masterId) return;
    setLoading(true);
    setError(null);
    try {
      const token = getToken ? await getToken() : null;
      const [m, lays] = await Promise.all([
        getMaster(token, masterId),
        listLayouts(token, masterId),
      ]);
      setMaster(m);
      setLayouts(lays);
      // Project's active pointer drives the "active" pill on this page.
      // We only know the project id once getMaster resolves, so this
      // fetch is sequential rather than parallel — acceptable: it's a
      // small JSON read and the master fetch dominates regardless.
      if (m?.project_id) {
        try {
          const { activeMasterId: aid } = await listMasters(token, m.project_id);
          setActiveMasterId(aid);
        } catch {
          /* non-fatal — pill won't render but page still works */
        }
      }
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [masterId, getToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const patchLayout = useCallback(
    async (layoutId, patch) => {
      // Optimistic apply locally; rollback on failure. We snapshot the
      // exact previous row rather than the whole array so concurrent
      // edits to other rows don't get clobbered by a rollback here.
      let prev = null;
      setLayouts((rows) => {
        return rows.map((r) => {
          if (r.id !== layoutId) return r;
          prev = r;
          return { ...r, ...optimisticOverlay(patch) };
        });
      });
      try {
        const token = getToken ? await getToken() : null;
        const updated = await updateLayout(token, layoutId, patch);
        setLayouts((rows) =>
          rows.map((r) => (r.id === layoutId ? { ...r, ...updated } : r)),
        );
        return updated;
      } catch (err) {
        if (prev) {
          setLayouts((rows) =>
            rows.map((r) => (r.id === layoutId ? prev : r)),
          );
        }
        throw err;
      }
    },
    [getToken],
  );

  const markDefault = useCallback(
    async (layoutId) => {
      const token = getToken ? await getToken() : null;
      const updated = await setLayoutDefault(token, layoutId);
      // Server cleared other defaults of the same kind — refresh the
      // whole list so the star pins the right card.
      setLayouts((rows) => {
        const target = rows.find((r) => r.id === layoutId);
        const kind = target ? target.user_kind ?? target.auto_kind : null;
        return rows.map((r) => {
          if (r.id === layoutId) return { ...r, ...updated };
          // Same kind on the same master? clear is_default — server did
          // it too but the UI shouldn't wait for the next refresh.
          const rkind = r.user_kind ?? r.auto_kind;
          if (rkind === kind) return { ...r, is_default: false };
          return r;
        });
      });
      return updated;
    },
    [getToken],
  );

  const activate = useCallback(async () => {
    if (!masterId) return null;
    const token = getToken ? await getToken() : null;
    const out = await activateMaster(token, masterId);
    setActiveMasterId(out?.active_master_id ?? masterId);
    return out;
  }, [masterId, getToken]);

  const remove = useCallback(async () => {
    if (!masterId) return;
    const token = getToken ? await getToken() : null;
    await deleteMaster(token, masterId);
  }, [masterId, getToken]);

  return {
    master,
    layouts,
    activeMasterId,
    isActive: !!master && activeMasterId === master.id,
    loading,
    error,
    refresh,
    patchLayout,
    markDefault,
    activate,
    remove,
  };
}

// Translate three-state PATCH sentinels to optimistic UI state.
//   * user_kind="" → null (cleared)
//   * notes="__CLEAR__" → null (cleared)
function optimisticOverlay(patch) {
  const out = { ...patch };
  if (out.user_kind === "") out.user_kind = null;
  if (out.notes === "__CLEAR__") out.notes = null;
  return out;
}
