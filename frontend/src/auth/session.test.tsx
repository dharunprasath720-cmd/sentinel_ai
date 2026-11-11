import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReactNode } from "react";
import { SessionProvider, useSession } from "./session";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function setup(fetchImpl: typeof fetch) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <SessionProvider fetchImpl={fetchImpl}>{children}</SessionProvider>
  );
  return renderHook(() => useSession(), { wrapper });
}

const loginFetch = (async (url: string) =>
  String(url).includes("/auth/login")
    ? json(200, { access_token: "abc", token_type: "bearer", role: "analyst" })
    : json(401, { detail: "Invalid or missing credentials" })) as unknown as typeof fetch;

describe("session", () => {
  it("login stores the session in sessionStorage only", async () => {
    const { result } = setup(loginFetch);
    await act(() => result.current.login("ana", "pw"));
    expect(result.current).toMatchObject({ token: "abc", role: "analyst", username: "ana" });
    expect(sessionStorage.getItem("sentinel.session")).toContain("abc");
    expect(localStorage.length).toBe(0);
  });

  it("logout clears it", async () => {
    const { result } = setup(loginFetch);
    await act(() => result.current.login("ana", "pw"));
    act(() => result.current.logout());
    expect(result.current.token).toBeNull();
    expect(sessionStorage.getItem("sentinel.session")).toBeNull();
  });

  it("a 401 from any call logs out", async () => {
    const { result } = setup(loginFetch);
    await act(() => result.current.login("ana", "pw"));
    await act(async () => { await result.current.client.get("/alerts").catch(() => undefined); });
    await waitFor(() => expect(result.current.token).toBeNull());
  });

  it("a failed login throws the server detail and stores nothing", async () => {
    const { result } = setup((async () => json(401, { detail: "Invalid or missing credentials" })) as typeof fetch);
    await expect(act(() => result.current.login("ana", "bad"))).rejects.toMatchObject({ status: 401 });
    expect(sessionStorage.getItem("sentinel.session")).toBeNull();
  });

  it("restores a stored session on load", () => {
    sessionStorage.setItem("sentinel.session", JSON.stringify({ token: "t", role: "viewer", username: "vic" }));
    const { result } = setup(loginFetch);
    expect(result.current).toMatchObject({ token: "t", role: "viewer", username: "vic" });
  });
});
