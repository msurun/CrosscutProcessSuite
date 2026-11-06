// frontend/src/authApi.ts
// Typed client for Crosscut authentication and user management API routes.
// Manages sessions, CSRF headers, error parsing, and event subscriptions for 401/403/428.

export const MIN_PASSWORD_LENGTH = 12;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly retry_after_s?: number;

  constructor(status: number, detail: string, retry_after_s?: number) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.retry_after_s = retry_after_s;
  }
}

export interface AuthUser {
  username: string;
  display_name: string;
}

export interface AuthSession {
  user: AuthUser;
  roles: string[];
  permissions: string[];
  csrf: string;
  must_change_password: boolean;
  stepup_valid?: boolean;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface PasswordChangePayload {
  old_password: string;
  new_password: string;
}

export interface StepUpPayload {
  password: string;
}

export interface StepUpResponse {
  ok: boolean;
  valid_for_s: number;
}

export interface OkResponse {
  ok: boolean;
}

export interface UserRecord {
  username: string;
  display_name: string;
  roles: string[];
  disabled: boolean;
  must_change_password: boolean;
  created_at?: string;
  password_changed_at?: string;
  failed_logins?: number;
  locked_until?: string | null;
  source?: string;
}

export interface UsersResponse {
  users: UserRecord[];
}

export interface CreateUserPayload {
  username: string;
  display_name: string;
  roles: string[];
  password: string;
  must_change_password: boolean;
}

export interface PatchUserPayload {
  display_name?: string;
  roles?: string[];
  disabled?: boolean;
  must_change_password?: boolean;
  password?: string;
}

type VoidListener = () => void;
type StepUpHandler = () => Promise<boolean>;

let currentCsrf: string | null = null;
let stepUpHandler: StepUpHandler | null = null;
const unauthorizedListeners = new Set<VoidListener>();
const passwordChangeRequiredListeners = new Set<VoidListener>();

/** Stores or clears the CSRF token in memory. */
export function setCsrfToken(csrf: string | null): void {
  currentCsrf = csrf;
}

/** Retrieves the current active CSRF token. */
export function getCsrfToken(): string | null {
  return currentCsrf;
}

/** Registers a callback invoked whenever an unauthenticated 401 response is received. */
export function subscribeUnauthorized(listener: VoidListener): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

/** Registers a callback for 403 responses indicating a mandatory password change. */
export function subscribePasswordChangeRequired(listener: VoidListener): () => void {
  passwordChangeRequiredListeners.add(listener);
  return () => {
    passwordChangeRequiredListeners.delete(listener);
  };
}

/** Registers an asynchronous handler to perform step-up authentication when challenged. */
export function setStepUpHandler(handler: StepUpHandler | null): void {
  stepUpHandler = handler;
}

function notifyListeners(listeners: Set<VoidListener>): void {
  for (const listener of listeners) {
    listener();
  }
}

function isStringArray(items: unknown): items is string[] {
  return Array.isArray(items) && items.every((item) => typeof item === "string");
}

function isValidAuthUser(data: unknown): data is AuthUser {
  if (typeof data !== "object" || data === null) {
    return false;
  }
  const obj = data as Record<string, unknown>;
  const hasValidUsername = typeof obj.username === "string" && obj.username.trim().length > 0;
  const hasValidDisplayName = typeof obj.display_name === "string";
  return hasValidUsername && hasValidDisplayName;
}

/** Validates whether an unknown response object matches the AuthSession schema. */
export function isValidAuthSession(data: unknown): data is AuthSession {
  if (typeof data !== "object" || data === null) {
    return false;
  }
  const obj = data as Record<string, unknown>;
  const hasBaseFields =
    isValidAuthUser(obj.user) &&
    isStringArray(obj.roles) &&
    isStringArray(obj.permissions) &&
    typeof obj.csrf === "string" &&
    typeof obj.must_change_password === "boolean";
  const hasValidStepUp = obj.stepup_valid === undefined || typeof obj.stepup_valid === "boolean";
  return hasBaseFields && hasValidStepUp;
}

interface ParsedErrorBody {
  detail: string;
  retry_after_s?: number;
}

function extractFastApiDetail(detailItem: unknown): string {
  if (typeof detailItem === "object" && detailItem !== null) {
    const message = (detailItem as Record<string, unknown>).msg;
    if (typeof message === "string") {
      return message;
    }
  }
  return String(detailItem);
}

function parseDetailField(detail: unknown, fallback: string): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map(extractFastApiDetail).join("; ");
  }
  return fallback;
}

function parseRetryAfterHeader(headerValue: string | null): number | undefined {
  if (!headerValue) {
    return undefined;
  }
  const parsedSeconds = Number(headerValue);
  const isValidInteger = Number.isInteger(parsedSeconds) && parsedSeconds >= 0;
  return isValidInteger ? parsedSeconds : undefined;
}

async function parseErrorBody(response: Response): Promise<ParsedErrorBody> {
  const headerRetry = parseRetryAfterHeader(response.headers.get("Retry-After"));
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const obj = body as Record<string, unknown>;
      const detail = parseDetailField(obj.detail, response.statusText);
      const bodyRetry = typeof obj.retry_after_s === "number" ? obj.retry_after_s : undefined;
      return { detail, retry_after_s: headerRetry ?? bodyRetry };
    }
  } catch {
    // Body was not valid JSON
  }
  return { detail: response.statusText, retry_after_s: headerRetry };
}

function buildHeaders(
  method: string,
  path: string,
  customHeaders?: Record<string, string>
): Record<string, string> {
  const headers: Record<string, string> = { ...customHeaders };
  if (method !== "GET" && method !== "HEAD" && path !== "/auth/login") {
    if (!currentCsrf) {
      throw new ApiError(403, "CSRF token missing for unsafe request");
    }
    headers["X-Crosscut-CSRF"] = currentCsrf;
  }
  return headers;
}

const API_PREFIX = "/api";

interface RequestAuthOptions {
  method?: string;
  body?: unknown;
  isRetry?: boolean;
  suppressUnauthorizedEvent?: boolean;
}

async function executeRequest(
  url: string,
  path: string,
  options: RequestAuthOptions
): Promise<Response> {
  const method = options.method ?? "GET";
  const customHeaders: Record<string, string> = {};
  if (options.body !== undefined) {
    customHeaders["Content-Type"] = "application/json";
  }
  const headers = buildHeaders(method, path, customHeaders);
  const init: RequestInit = {
    method,
    headers,
    credentials: "same-origin",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  };
  return fetch(url, init);
}

function handle401And403Events(status: number, detail: string, suppress401?: boolean): void {
  if (status === 401 && !suppress401) {
    notifyListeners(unauthorizedListeners);
  }
  if (status === 403 && detail === "password_change_required") {
    notifyListeners(passwordChangeRequiredListeners);
  }
}

async function tryStepUpRetry(
  url: string,
  path: string,
  options: RequestAuthOptions
): Promise<Response | null> {
  if (path === "/auth/stepup" || !stepUpHandler) {
    return null;
  }
  const wasHandled = await stepUpHandler();
  if (!wasHandled) {
    return null;
  }
  return executeRequest(url, path, { ...options, isRetry: true });
}

async function handleResponseError(
  response: Response,
  url: string,
  path: string,
  options: RequestAuthOptions
): Promise<Response> {
  const { detail, retry_after_s } = await parseErrorBody(response);
  handle401And403Events(response.status, detail, options.suppressUnauthorizedEvent);

  if (response.status === 428 && detail === "step_up_required" && !options.isRetry) {
    const retriedResponse = await tryStepUpRetry(url, path, options);
    if (retriedResponse) {
      return retriedResponse;
    }
  }
  throw new ApiError(response.status, detail, retry_after_s);
}

async function requestAuth<T>(path: string, options: RequestAuthOptions = {}): Promise<T> {
  const url = `${API_PREFIX}${path}`;
  let response = await executeRequest(url, path, options);
  if (!response.ok) {
    response = await handleResponseError(response, url, path, options);
    if (!response.ok) {
      const { detail, retry_after_s } = await parseErrorBody(response);
      throw new ApiError(response.status, detail, retry_after_s);
    }
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const json: unknown = await response.json();
  return json as T;
}

/** Authenticates user credentials and initializes the session. */
export async function login(payload: LoginPayload): Promise<AuthSession> {
  const data = await requestAuth<unknown>("/auth/login", {
    method: "POST",
    body: payload,
    suppressUnauthorizedEvent: true,
  });
  if (!isValidAuthSession(data)) {
    throw new ApiError(500, "Invalid auth response from server");
  }
  setCsrfToken(data.csrf);
  return data;
}

/** Logs out the current user and discards session tokens. */
export async function logout(): Promise<OkResponse> {
  try {
    return await requestAuth<OkResponse>("/auth/logout", { method: "POST" });
  } finally {
    setCsrfToken(null);
  }
}

/** Fetches the currently authenticated session profile. */
export async function fetchMe(): Promise<AuthSession> {
  const data = await requestAuth<unknown>("/auth/me");
  if (!isValidAuthSession(data)) {
    throw new ApiError(500, "Invalid auth response from server");
  }
  setCsrfToken(data.csrf);
  return data;
}

/** Changes password for the active authenticated session. */
export async function changePassword(payload: PasswordChangePayload): Promise<OkResponse> {
  return requestAuth<OkResponse>("/auth/password", { method: "POST", body: payload });
}

/** Elevates privilege for sensitive actions via step-up password confirmation. */
export async function stepUp(payload: StepUpPayload): Promise<StepUpResponse> {
  return requestAuth<StepUpResponse>("/auth/stepup", { method: "POST", body: payload });
}

/** Retrieves the list of managed users. */
export async function fetchUsers(): Promise<UsersResponse> {
  return requestAuth<UsersResponse>("/auth/users");
}

/** Creates a new user record. */
export async function createUser(payload: CreateUserPayload): Promise<UserRecord> {
  return requestAuth<UserRecord>("/auth/users", { method: "POST", body: payload });
}

/** Modifies existing user properties by username. */
export async function patchUser(username: string, payload: PatchUserPayload): Promise<UserRecord> {
  const encoded = encodeURIComponent(username);
  return requestAuth<UserRecord>(`/auth/users/${encoded}`, { method: "PATCH", body: payload });
}

/** Deletes a user by username. */
export async function deleteUser(username: string): Promise<OkResponse> {
  const encoded = encodeURIComponent(username);
  return requestAuth<OkResponse>(`/auth/users/${encoded}`, { method: "DELETE" });
}
