// 打包后前后端同源，用相对路径即可——省掉 CORS 预检和写死的主机端口。
// 开发时 next dev 与后端不同端口，用 NEXT_PUBLIC_API_BASE_URL 覆盖。
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "/api";

const DEFAULT_TIMEOUT_MS = 20_000;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export type ApiInit = RequestInit & { timeoutMs?: number };

function withTimeout(init?: ApiInit): { init: RequestInit; done: () => void } {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...rest } = init ?? {};
  // 没有超时的话，后端一慢请求就一直挂着，轮询会不断叠加。
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  return {
    init: { ...rest, signal: controller.signal },
    done: () => clearTimeout(timer),
  };
}

/**
 * 只在真的有请求体时才带 Content-Type。GET 上带它会让请求变成"非简单请求"，
 * 每个 GET 前面都要多一次 CORS 预检 OPTIONS（实测请求数直接翻倍）。
 */
function jsonHeaders(init?: ApiInit): HeadersInit | undefined {
  const hasBody = init?.body !== undefined && init?.body !== null;
  if (!hasBody) return init?.headers;
  return { "Content-Type": "application/json", ...init?.headers };
}

async function toApiError(response: Response): Promise<ApiError> {
  const payload = await response.json().catch(() => null);
  const detail = (payload as { detail?: unknown } | null)?.detail;
  return new ApiError(
    typeof detail === "string" ? detail : `请求失败（${response.status}）`,
    response.status,
  );
}

export async function api<T>(path: string, init?: ApiInit): Promise<T> {
  const { init: requestInit, done } = withTimeout(init);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...requestInit,
      headers: jsonHeaders(init),
      cache: "no-store",
    });
    if (!response.ok) throw await toApiError(response);
    return (await response.json()) as T;
  } finally {
    done();
  }
}

export type Conditional<T> = { data: T | null; etag: string | null; notModified: boolean };

/** 带 ETag 的读取：内容没变时后端返回 304，只花一个空响应。 */
export async function apiConditional<T>(
  path: string,
  etag: string | null,
  init?: ApiInit,
): Promise<Conditional<T>> {
  const { init: requestInit, done } = withTimeout(init);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...requestInit,
      headers: {
        ...(etag ? { "If-None-Match": etag } : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
    if (response.status === 304) {
      return { data: null, etag, notModified: true };
    }
    if (!response.ok) throw await toApiError(response);
    return {
      data: (await response.json()) as T,
      etag: response.headers.get("ETag"),
      notModified: false,
    };
  } finally {
    done();
  }
}

export function scriptDownloadUrl(topicId: string): string {
  return `${API_BASE}/topics/${topicId}/script/download`;
}

export function productionPackageDownloadUrl(topicId: string): string {
  return `${API_BASE}/topics/${topicId}/production-package/download`;
}
