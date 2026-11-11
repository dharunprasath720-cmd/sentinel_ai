import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useLiveStream } from "./useLiveStream";

function controlled() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({ start(c) { ctrl = c; } });
  return {
    response: new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
    push: (obj: object) => ctrl.enqueue(enc.encode(`data: ${JSON.stringify(obj)}\n\n`)),
    close: () => ctrl.close(),
  };
}
const ev = (id: string) => ({ external_id: id, risk_level: "HIGH" });

afterEach(() => vi.useRealTimers());

describe("useLiveStream", () => {
  it("delivers events newest first and caps at maxRows", async () => {
    const s = controlled();
    const fetchImpl = vi.fn(async () => s.response) as unknown as typeof fetch;
    const { result } = renderHook(() => useLiveStream({ token: "t", onUnauthorized: vi.fn(), maxRows: 2, fetchImpl }));
    await waitFor(() => expect(result.current.state).toBe("open"));
    act(() => { s.push(ev("a")); s.push(ev("b")); s.push(ev("c")); });
    await waitFor(() => expect(result.current.events.map((e) => e.external_id)).toEqual(["c", "b"]));
    const headers = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer t");
  });

  it("401 closes without retrying and calls onUnauthorized", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 401 })) as unknown as typeof fetch;
    const onUnauthorized = vi.fn();
    const { result } = renderHook(() => useLiveStream({ token: "t", onUnauthorized, fetchImpl }));
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(result.current.state).toBe("closed");
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("a network error reconnects with backoff", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const s = controlled();
    const fetchImpl = vi.fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(s.response) as unknown as typeof fetch;
    const { result } = renderHook(() => useLiveStream({ token: "t", onUnauthorized: vi.fn(), fetchImpl }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(result.current.state).toBe("reconnecting");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(result.current.state).toBe("open");
  });

  it("paused hides new events and resuming shows later ones", async () => {
    const s = controlled();
    const fetchImpl = vi.fn(async () => s.response) as unknown as typeof fetch;
    const { result } = renderHook(() => useLiveStream({ token: "t", onUnauthorized: vi.fn(), fetchImpl }));
    await waitFor(() => expect(result.current.state).toBe("open"));
    act(() => result.current.setPaused(true));
    act(() => s.push(ev("hidden")));
    await new Promise((r) => setTimeout(r, 30));
    expect(result.current.events).toEqual([]);
    act(() => result.current.setPaused(false));
    act(() => s.push(ev("shown")));
    await waitFor(() => expect(result.current.events.map((e) => e.external_id)).toEqual(["shown"]));
  });

  it("aborts the request on unmount", async () => {
    const s = controlled();
    const fetchImpl = vi.fn(async () => s.response) as unknown as typeof fetch;
    const { result, unmount } = renderHook(() => useLiveStream({ token: "t", onUnauthorized: vi.fn(), fetchImpl }));
    await waitFor(() => expect(result.current.state).toBe("open"));
    const signal = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1].signal as AbortSignal;
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it("does nothing without a token", () => {
    const fetchImpl = vi.fn() as unknown as typeof fetch;
    const { result } = renderHook(() => useLiveStream({ token: null, onUnauthorized: vi.fn(), fetchImpl }));
    expect(result.current.state).toBe("closed");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
