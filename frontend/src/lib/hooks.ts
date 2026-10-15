import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Contact } from "../api/client";

export const POLL_INTERVAL_MS = 1500;
export const POLL_TIMEOUT_MS = 120_000; // must exceed the backend model timeout (90 s)

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

type LoadState = "loading" | "ready" | "not_found" | "error";

/**
 * Loads a contact and, while enrichment is pending, polls every 1.5 s.
 * Polling stops after 120 s and sets `timedOut` (the UI shows a Retry).
 */
export function useContact(id: string) {
  const [contact, setContact] = useState<Contact | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const pendingSince = useRef<number | null>(null);
  const [pollEpoch, setPollEpoch] = useState(0);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState((s) => (s === "ready" ? s : "loading"));
      setError(null);
      try {
        const c = await api.getContact(id, { signal });
        setContact(c);
        setState("ready");
      } catch (e) {
        if (signal?.aborted) return;
        if (e instanceof ApiError && e.status === 404) {
          setState("not_found");
        } else {
          setError(e instanceof ApiError ? e.message : "Couldn't load this contact.");
          setState("error");
        }
      }
    },
    [id],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    pendingSince.current = null;
    setTimedOut(false);
    setContact(null);
    setState("loading");
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const pending = contact?.enrichment_status === "pending";

  useEffect(() => {
    if (!pending || timedOut) {
      if (!pending) pendingSince.current = null;
      return;
    }
    if (pendingSince.current === null) pendingSince.current = Date.now();
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (pendingSince.current !== null && Date.now() - pendingSince.current >= POLL_TIMEOUT_MS) {
        setTimedOut(true);
        return;
      }
      try {
        const c = await api.getContact(id, { signal: ctrl.signal, timeoutMs: 10_000 });
        if (ctrl.signal.aborted) return;
        setPollError(null);
        setContact(c);
        if (c.enrichment_status !== "pending") return;
      } catch (e) {
        if (ctrl.signal.aborted) return;
        if (e instanceof ApiError && e.status === 404) {
          setState("not_found");
          return;
        }
        // Transient errors: keep polling until the 120 s budget is spent.
        setPollError(e instanceof ApiError ? e.message : "Lost connection. Still trying…");
      }
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    };
    timer = setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      ctrl.abort();
      clearTimeout(timer);
    };
  }, [pending, timedOut, id, pollEpoch]);

  /** Replace the contact with a fresh server copy (e.g. after a mutation). */
  const replace = useCallback((c: Contact) => {
    if (c.enrichment_status === "pending") {
      pendingSince.current = Date.now();
      setTimedOut(false);
      setPollEpoch((n) => n + 1);
    }
    setContact(c);
  }, []);

  /** Restart polling after a timeout without re-triggering enrichment. */
  const resumePolling = useCallback(() => {
    pendingSince.current = Date.now();
    setTimedOut(false);
    setPollEpoch((n) => n + 1);
  }, []);

  return { contact, state, error, timedOut, pollError, reload: () => load(), replace, resumePolling };
}
