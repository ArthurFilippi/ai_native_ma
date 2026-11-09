import { useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: Error };

interface Settled<T> {
  load: () => Promise<T>;
  data?: T;
  error?: Error;
}

function toError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}

// Runs `load` whenever its identity changes (wrap it in useCallback). The status is derived, so
// a new `load` shows "loading" at once without setting state inside the effect.
export function useAsync<T>(load: () => Promise<T>): AsyncState<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    let live = true;
    load().then(
      (data) => {
        if (live) setSettled({ load, data });
      },
      (error: unknown) => {
        if (live) setSettled({ load, error: toError(error) });
      },
    );
    return () => {
      live = false;
    };
  }, [load]);

  if (settled === null || settled.load !== load) return { status: "loading" };
  if (settled.error) return { status: "error", error: settled.error };
  return { status: "ready", data: settled.data as T };
}
