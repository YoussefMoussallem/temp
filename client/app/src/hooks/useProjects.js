import { useCallback, useEffect, useState } from "react";
import * as api from "../api";

export function useProjects(getToken) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getToken ? await getToken() : null;
      const list = await api.listProjects(token);
      setProjects(list);
      return list;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return [];
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = useCallback(
    async (name, description = null) => {
      const token = getToken ? await getToken() : null;
      const project = await api.createProject(token, { name, description });
      setProjects((prev) => [project, ...prev]);
      return project;
    },
    [getToken],
  );

  const rename = useCallback(
    async (id, name) => {
      const token = getToken ? await getToken() : null;
      const updated = await api.renameProject(token, id, { name });
      setProjects((prev) => prev.map((p) => (p.id === id ? updated : p)));
      return updated;
    },
    [getToken],
  );

  const remove = useCallback(
    async (id) => {
      const token = getToken ? await getToken() : null;
      await api.deleteProject(token, id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
    },
    [getToken],
  );

  return { projects, loading, error, refresh, create, rename, remove };
}
