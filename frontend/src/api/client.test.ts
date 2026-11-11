import { describe, expect, it, vi } from "vitest";
import { ApiError, createClient } from "./client";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function make(fetchImpl: typeof fetch, token: string | null = "tok") {
  const onUnauthorized = vi.fn();
  return { onUnauthorized, client: createClient({ getToken: () => token, onUnauthorized, fetchImpl }) };
}

describe("api client", () => {
  it("attaches the bearer token and serialises query params", async () => {
    const f = vi.fn(async () => json(200, { ok: 1 }));
    const { client } = make(f as unknown as typeof fetch);
    await client.get("/transactions", { limit: 5, level: undefined, source: "synthetic" });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/transactions?limit=5&source=synthetic");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("posts JSON bodies", async () => {
    const f = vi.fn(async () => json(200, {}));
    const { client } = make(f as unknown as typeof fetch);
    await client.post("/cases", { alert_ids: [1] });
    const init = (f.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"alert_ids":[1]}');
  });

  it("maps a 403 detail to ApiError", async () => {
    const { client } = make((async () => json(403, { detail: "role not allowed" })) as typeof fetch);
    await expect(client.get("/x")).rejects.toMatchObject({ status: 403, detail: "role not allowed" });
  });

  it("401 calls onUnauthorized once then throws", async () => {
    const { client, onUnauthorized } = make((async () => json(401, { detail: "Invalid or missing credentials" })) as typeof fetch);
    await expect(client.get("/x")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('a non-string detail becomes "Invalid request"', async () => {
    const { client } = make((async () => json(422, { detail: [{ loc: ["query"], msg: "bad" }] })) as typeof fetch);
    await expect(client.get("/x")).rejects.toMatchObject({ status: 422, detail: "Invalid request" });
  });

  it("a network failure becomes an ApiError with status 0", async () => {
    const { client } = make((async () => { throw new TypeError("offline"); }) as typeof fetch);
    await expect(client.get("/x")).rejects.toMatchObject({ status: 0 });
  });
});
