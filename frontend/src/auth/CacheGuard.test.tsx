import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { CacheGuard } from "./CacheGuard";
import { SessionProvider, useSession } from "./session";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const fetchImpl = (async () => json(200, { access_token: "abc", token_type: "bearer", role: "analyst" })) as unknown as typeof fetch;

function setup() {
  const qc = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <SessionProvider fetchImpl={fetchImpl}><CacheGuard />{children}</SessionProvider>
    </QueryClientProvider>
  );
  return { qc, ...renderHook(() => useSession(), { wrapper }) };
}

describe("CacheGuard", () => {
  it("drops every cached query when the user signs out, so the next user never sees it", async () => {
    const { qc, result } = setup();
    await act(() => result.current.login("ana", "pw"));
    qc.setQueryData(["overview", "synthetic"], { business: "X" });
    act(() => result.current.logout());
    expect(qc.getQueryData(["overview", "synthetic"])).toBeUndefined();
  });

  it("also clears the cache when a different user signs in", async () => {
    const { qc, result } = setup();
    await act(() => result.current.login("ana", "pw"));
    qc.setQueryData(["cases"], [{ id: 1 }]);
    await act(() => result.current.login("bob", "pw"));
    expect(qc.getQueryData(["cases"])).toBeUndefined();
  });

  it("keeps the cache while the same session continues", async () => {
    const { qc, result } = setup();
    await act(() => result.current.login("ana", "pw"));
    qc.setQueryData(["cases"], [{ id: 1 }]);
    expect(qc.getQueryData(["cases"])).toEqual([{ id: 1 }]);
    expect(result.current.token).toBe("abc");
  });
});
