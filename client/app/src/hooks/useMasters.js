// Masters list + actions for a single project.
//
// Consumers: MastersPage. The hook is project-scoped; passing a
// different projectId triggers a fresh load. Callers can opt out of
// the auto-load by passing ``null``.
//
// Surface:
//   * masters[]        — current list, newest-first as the API returns
//   * loading          — true while the initial load (or a manual
//                        ``refresh()``) is in flight
//   * error            — last error, cleared on successful refresh
//   * activeMasterId   — set after a successful activate(); used by the
//                        page to pin the "active" pill without a refetch
//   * upload(file, fonts?) — multipart POST + refresh; ``fonts`` is
//                            an optional array of font File objects
//                            bundled with the master upload
//   * activate(id)     — flips active_master_id, optimistic + refresh
//   * remove(id)       — DELETE + refresh

import { useCallback, useEffect, useState } from "react";
import {
  listMasters,
  uploadMaster,
  activateMaster,
  deleteMaster,
} from "../api/masters.js";

export function useMasters(projectId, getToken) {
  const [masters, setMasters] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeMasterId, setActiveMasterId] = useState(null);

  const refresh = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const token = getToken ? await getToken() : null;
      // Phase 2.0: listMasters returns { masters, activeMasterId } —
      // pin the active card from the server so re-mounting the page
      // (or a fresh navigation) shows the correct active state.
      const { masters: list, activeMasterId: activeFromServer } =
        await listMasters(token, projectId);
      setMasters(list);
      setActiveMasterId(activeFromServer);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [projectId, getToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const upload = useCallback(
    async (file, fonts = []) => {
      const token = getToken ? await getToken() : null;
      await uploadMaster(token, projectId, file, null, fonts);
      await refresh();
    },
    [projectId, getToken, refresh],
  );

  const activate = useCallback(
    async (masterId) => {
      const token = getToken ? await getToken() : null;
      const out = await activateMaster(token, masterId);
      setActiveMasterId(out?.active_master_id ?? masterId);
      // No need to refresh — the list shape didn't change.
    },
    [getToken],
  );

  const remove = useCallback(
    async (masterId) => {
      const token = getToken ? await getToken() : null;
      await deleteMaster(token, masterId);
      // The server cascades active_master_id to NULL via FK ON DELETE
      // SET NULL; refresh() re-reads it. We optimistically clear here
      // so the UI doesn't flash stale.
      if (activeMasterId === masterId) setActiveMasterId(null);
      await refresh();
    },
    [getToken, refresh, activeMasterId],
  );

  return {
    masters,
    loading,
    error,
    activeMasterId,
    refresh,
    upload,
    activate,
    remove,
  };
}
