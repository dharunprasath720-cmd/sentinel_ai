import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { ApiError, type ApiClient, type Params } from "./api/client";
import type { Role } from "./api/types";
import { SessionContext, type SessionValue } from "./auth/session";
import { SourceProvider } from "./source";

export interface Call { method: "GET" | "POST"; path: string; params?: Params; body?: unknown }
type Handler = (call: Call) => unknown;

/** A scripted API client: routes are keyed "GET /path" or "POST /path"; a handler may return a value
 *  or throw an ApiError. Unknown routes answer 404. Every call is recorded in `calls`. */
export function fakeClient(routes: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  async function run(method: "GET" | "POST", path: string, params?: Params, body?: unknown) {
    const call: Call = { method, path, params, body };
    calls.push(call);
    const h = routes[`${method} ${path}`];
    if (h === undefined) throw new ApiError(404, "Not found");
    return typeof h === "function" ? (h as Handler)(call) : h;
  }
  const client: ApiClient & { calls: Call[] } = {
    calls,
    get: ((path: string, params?: Params) => run("GET", path, params)) as ApiClient["get"],
    post: ((path: string, body?: unknown) => run("POST", path, undefined, body)) as ApiClient["post"],
  };
  return client;
}

export function renderPage(ui: ReactElement, opts: { client: ApiClient; role?: Role; route?: string }) {
  const session: SessionValue = {
    token: "t", role: opts.role ?? "analyst", username: "ana", login: vi.fn(), logout: vi.fn(), client: opts.client,
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SessionContext.Provider value={session}>
        <SourceProvider>
          <MemoryRouter initialEntries={[opts.route ?? "/"]}>{ui}</MemoryRouter>
        </SourceProvider>
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}
