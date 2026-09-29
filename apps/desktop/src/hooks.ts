import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "./api";
import type { ApiErrorBody } from "./types";

/** Load data from the API; `reload()` refreshes it. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (path === null) return;
    const mine = ++seq.current;
    setLoading(true);
    try {
      const d = await api.get<T>(path);
      if (mine === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (mine === seq.current) setError(errorMessage(e));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}

/** Run an action with busy/error state. Returns the action's result or undefined on failure. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const run = useCallback(async <R,>(label: string, fn: () => Promise<R>, success?: string): Promise<R | undefined> => {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      const r = await fn();
      if (success) setNotice(success);
      return r;
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setBusy(null);
    }
  }, []);

  return { busy, error, notice, run, setError, setNotice };
}

export type Quality = "draft" | "final";

/** Render quality selector state, initialised from the user's default in Settings. */
export function useDefaultQuality(): [Quality, (q: Quality) => void] {
  const [quality, setQuality] = useState<Quality | null>(null);
  const [fallback, setFallback] = useState<Quality>("final");
  useEffect(() => {
    let alive = true;
    api
      .get<{ default_quality: Quality }>("/api/preferences")
      .then((p) => alive && setFallback(p.default_quality))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  return [quality ?? fallback, setQuality];
}
