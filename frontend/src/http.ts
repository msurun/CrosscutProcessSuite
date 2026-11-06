// frontend/src/http.ts
// The one request layer every API call goes through: same-origin credentials, the CSRF header on
// unsafe methods, 401 -> "session ended" event, 428 -> step-up dialog and one retry,
// 403 password_change_required -> change-password event. With auth off none of these fire.

import {
  getCsrfToken,
  notifyPasswordChangeRequired,
  notifyUnauthorized,
  runStepUpHandler,
} from "./authApi";

const CSRF_HEADER = "X-Crosscut-CSRF";
const SAFE_METHODS: readonly string[] = ["GET", "HEAD", "OPTIONS"];
const STEP_UP_DETAIL = "step_up_required";
const PASSWORD_CHANGE_DETAIL = "password_change_required";

function headerRecord(headers: HeadersInit | undefined): Record<string, string> {
  if (headers === undefined) return {};
  if (Array.isArray(headers) || headers instanceof Headers) {
    return Object.fromEntries(new Headers(headers).entries());
  }
  return { ...headers };
}

/** Builds the request init: same-origin credentials plus the CSRF header on unsafe methods. */
export function withAuthInit(init: RequestInit = {}): RequestInit {
  const method = (init.method ?? "GET").toUpperCase();
  const csrf = getCsrfToken();
  const addCsrf = csrf !== null && !SAFE_METHODS.includes(method);
  const merged: RequestInit = { ...init, credentials: "same-origin" };
  if (addCsrf) merged.headers = { ...headerRecord(init.headers), [CSRF_HEADER]: csrf };
  return merged;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.clone().json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" ? detail : "";
  } catch {
    return "";
  }
}

async function react(response: Response, retry: () => Promise<Response>): Promise<Response> {
  if (response.status === 401) {
    notifyUnauthorized();
    return response;
  }
  if (response.status !== 428 && response.status !== 403) return response;
  const detail = await errorDetail(response);
  if (response.status === 403 && detail === PASSWORD_CHANGE_DETAIL) notifyPasswordChangeRequired();
  if (response.status === 428 && detail === STEP_UP_DETAIL && (await runStepUpHandler())) {
    return retry();
  }
  return response;
}

/**
 * fetch() with the shared auth behaviour. Resolves to the final Response (never throws for HTTP
 * statuses), so callers keep their own error handling. A 428 step-up challenge is retried once.
 */
export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const first = await fetch(url, withAuthInit(init));
  return react(first, async () => {
    const second = await fetch(url, withAuthInit(init));
    if (second.status === 401) notifyUnauthorized();
    return second;
  });
}
