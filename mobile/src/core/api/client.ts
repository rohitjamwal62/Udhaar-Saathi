import { config } from '../config';
import { newId } from '../ids';
import { tokenStore } from '../auth/tokenStore';

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string, public details?: unknown) {
    super(message);
  }
  get isNetwork() { return this.status === 0; }
  get isServer() { return this.status >= 500; }
}

let onSessionExpired: (() => void) | null = null;
export const setSessionExpiredHandler = (fn: () => void) => { onSessionExpired = fn; };

// Free hosting puts an idle server to sleep; waking it takes up to ~60 s, so be patient on the first request.
const TIMEOUT_MS = 75000;

async function rawFetch(path: string, init: RequestInit, token?: string | null): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    return await fetch(`${config.apiUrl}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-Request-ID': newId(), // correlation id for server logs
        'X-App-Version': config.appVersion,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your internet connection.');
  } finally {
    clearTimeout(timer);
  }
}

let refreshing: Promise<boolean> | null = null;
async function refreshTokens(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      const refresh = await tokenStore.getRefresh();
      if (!refresh) return false;
      try {
        const res = await rawFetch('/auth/token/refresh', {
          method: 'POST',
          body: JSON.stringify({ refresh }),
        });
        if (!res.ok) return false;
        const data = (await res.json()) as { access: string; refresh: string };
        await tokenStore.setTokens(data.access, data.refresh); // refresh tokens rotate
        return true;
      } catch {
        return false;
      }
    })().finally(() => { refreshing = null; });
  }
  return refreshing;
}

function safeJson(t: string): unknown {
  try { return JSON.parse(t); } catch { return null; }
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) {
    const b = body as { detail?: string; code?: string } | null;
    throw new ApiError(res.status, b?.detail ?? `Request failed (${res.status})`, b?.code, body);
  }
  return body as T;
}

export async function api<T>(
  path: string,
  opts: { method?: string; body?: unknown; auth?: boolean } = {},
): Promise<T> {
  const { method = 'GET', body, auth = true } = opts;
  const init: RequestInit = { method, body: body === undefined ? undefined : JSON.stringify(body) };
  let res = await rawFetch(path, init, auth ? await tokenStore.getAccess() : null);
  if (res.status === 401 && auth) {
    if (await refreshTokens()) {
      res = await rawFetch(path, init, await tokenStore.getAccess());
    } else {
      onSessionExpired?.();
    }
  }
  return parse<T>(res);
}

/** Fire-and-forget ping at app start so a sleeping free server is already waking while the user types. */
export function warmUpServer(): void {
  try {
    const origin = config.apiUrl.replace(/\/api\/v1\/?$/, '');
    void fetch(`${origin}/health/live`).catch(() => undefined);
  } catch {
    /* never let a warm-up break the app */
  }
}
