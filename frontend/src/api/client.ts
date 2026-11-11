export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export type Params = Record<string, string | number | undefined>;
export interface ApiClient {
  get<T>(path: string, params?: Params): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
}
export interface ClientOptions {
  getToken: () => string | null;
  onUnauthorized: () => void;
  fetchImpl?: typeof fetch;
  baseUrl?: string;
}

export function createClient(opts: ClientOptions): ApiClient {
  const { getToken, onUnauthorized, baseUrl = "" } = opts;

  async function request<T>(method: string, path: string, params?: Params, body?: unknown): Promise<T> {
    const query = new URLSearchParams();
    for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined) query.set(k, String(v));
    const qs = query.toString();
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await (opts.fetchImpl ?? fetch)(`${baseUrl}${path}${qs ? `?${qs}` : ""}`, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "Network error: the server could not be reached");
    }
    let data: unknown = null;
    try { data = await res.json(); } catch { /* empty or non-JSON body */ }
    if (!res.ok) {
      if (res.status === 401) onUnauthorized();
      const detail = (data as { detail?: unknown } | null)?.detail;
      throw new ApiError(res.status, typeof detail === "string" ? detail : data === null ? `HTTP ${res.status}` : "Invalid request");
    }
    return data as T;
  }

  return {
    get: (path, params) => request("GET", path, params),
    post: (path, body) => request("POST", path, undefined, body ?? {}),
  };
}
