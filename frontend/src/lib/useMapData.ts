import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { MapResponse } from "../api/types";

export function useMapData(mapId: string | undefined) {
  const [data, setData] = useState<MapResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!mapId) return;
    try {
      setData(await api.getMap(mapId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [mapId]);

  useEffect(() => {
    setData(null);
    reload();
  }, [reload]);

  return { data, setData, error, reload };
}
