import { errorMessage, qs, type ApiResult, type QueryParams } from "./client";

/**
 * API calls from client components, through the same-origin gateway (`app/api/v1/[...path]`), which adds
 * the session token server-side. Same result shape as `apiFetch`.
 */
export async function browserApi<T>(
  path: string,
  { method = "GET", body, query, signal }: { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown; query?: QueryParams | URLSearchParams; signal?: AbortSignal } = {},
): Promise<ApiResult<T>> {
  const search = query instanceof URLSearchParams ? (query.size ? `?${query}` : "") : qs(query ?? {});
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}${search}`, {
      method,
      headers: body === undefined ? { accept: "application/json" } : { accept: "application/json", "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    return { ok: false, kind: "unreachable", message: err instanceof Error ? err.message : String(err) };
  }
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = text;
  }
  if (!res.ok) {
    const detail = (json as { detail?: unknown } | null)?.detail ?? json;
    return { ok: false, kind: "http", status: res.status, message: errorMessage(res.status, detail), detail };
  }
  return { ok: true, data: json as T };
}
