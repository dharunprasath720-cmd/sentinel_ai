import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveEvent } from "../api/types";
import { SseParser } from "./sse";

export type StreamState = "connecting" | "open" | "reconnecting" | "closed";
export interface LiveStreamOptions {
  token: string | null;
  onUnauthorized: () => void;
  maxRows?: number;
  fetchImpl?: typeof fetch;
}

const MIN_DELAY = 1000;
const MAX_DELAY = 15000;

/** Reads /stream/events with fetch (so the token travels in a header, never a URL), keeps the
 *  newest `maxRows` events, reconnects with capped backoff, and stops for good on a 401. */
export function useLiveStream({ token, onUnauthorized, maxRows = 200, fetchImpl }: LiveStreamOptions) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [state, setState] = useState<StreamState>(token ? "connecting" : "closed");
  const [paused, setPausedState] = useState(false);
  const pausedRef = useRef(false);
  const unauthorizedRef = useRef(onUnauthorized);
  unauthorizedRef.current = onUnauthorized;

  const setPaused = useCallback((p: boolean) => { pausedRef.current = p; setPausedState(p); }, []);
  const clear = useCallback(() => setEvents([]), []);

  useEffect(() => {
    if (!token) { setState("closed"); return; }
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();

    const sleep = (ms: number) => new Promise<void>((resolve) => { timer = setTimeout(resolve, ms); });

    async function run() {
      let delay = MIN_DELAY;
      let attempt = 0;
      while (!stopped) {
        setState(attempt === 0 ? "connecting" : "reconnecting");
        attempt += 1;
        try {
          const res = await (fetchImpl ?? fetch)("/stream/events", {
            headers: { Authorization: `Bearer ${token}` }, signal: abort.signal,
          });
          if (res.status === 401) { setState("closed"); unauthorizedRef.current(); return; }
          if (!res.ok || !res.body) throw new Error(`stream failed: HTTP ${res.status}`);
          setState("open");
          delay = MIN_DELAY;
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          const parser = new SseParser();
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            for (const item of parser.push(decoder.decode(value, { stream: true }))) {
              const ev = item as LiveEvent;
              if (pausedRef.current || typeof ev?.external_id !== "string") continue;
              setEvents((prev) => [ev, ...prev].slice(0, maxRows));
            }
          }
        } catch {
          if (stopped) return;
        }
        if (stopped) return;
        setState("reconnecting");
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      }
    }

    void run();
    return () => { stopped = true; abort.abort(); if (timer) clearTimeout(timer); };
  }, [token, maxRows, fetchImpl]);

  return { events, state, paused, setPaused, clear };
}
