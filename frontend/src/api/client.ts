/**
 * The only way the frontend reaches data: same-origin calls to the FastAPI backend
 * under /api. No database or storage credentials ever exist here.
 *
 * Auth tokens live in HttpOnly cookies the page cannot read (SEC-09). The page only
 * reads the CSRF cookie and echoes it in X-CSRF-Token on state-changing requests.
 * When the 30-minute access token has lapsed, one silent refresh is attempted.
 */
export type Health = { status: "ok" | "degraded"; database: "ok" | "unavailable" };

export type User = {
  user_id: number;
  username: string;
  email: string;
  role: string;
  permissions: string[];
  must_change_password: boolean;
  mfa_enabled: boolean;
  mfa_required: boolean;
  mfa_verified: boolean;
};

export type NextStep = "change_password" | "mfa_setup" | "mfa_verify" | "done";
export type LoginResult = { user: User; next_step: NextStep };
export type MfaSetup = { otpauth_uri: string; qr_svg_data_uri: string; manual_entry_key: string };

type ErrorBody = { error?: { code?: string; message?: string; correlation_id?: string } };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public correlationId?: string,
  ) {
    super(message);
  }
}

const NO_REFRESH = new Set(["/auth/login", "/auth/refresh", "/auth/logout"]);

export function csrfToken(): string {
  const match = document.cookie.split("; ").find((c) => c.startsWith("mem_csrf="));
  return match ? decodeURIComponent(match.slice("mem_csrf=".length)) : "";
}

/** UC2 messages for requests that never get a server answer. */
export const TIMEOUT_MESSAGE = "The request is taking longer than expected. Please try again.";
export const NETWORK_MESSAGE =
  "We could not reach the server. Please check your connection and try again. " +
  "If the problem continues, contact your system administrator.";
/** UC2: data requests give up after 5 seconds. */
export const DATA_TIMEOUT_MS = 5000;

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  retry = true,
  timeoutMs?: number,
  asFile = false,
): Promise<T> {
  const headers: Record<string, string> = { Accept: asFile ? "*/*" : "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  const controller = timeoutMs ? new AbortController() : undefined;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : undefined;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller?.signal,
    });
  } catch {
    if (controller?.signal.aborted) throw new ApiError(0, "timeout", TIMEOUT_MESSAGE);
    throw new ApiError(0, "network", NETWORK_MESSAGE);
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (response.ok) return (asFile ? await toDownload(response) : await response.json()) as T;

  const parsed = (await response.json().catch(() => ({}))) as ErrorBody;
  const error = new ApiError(
    response.status,
    parsed.error?.code ?? `http_${response.status}`,
    parsed.error?.message ?? `Request failed (${response.status})`,
    parsed.error?.correlation_id,
  );
  const lapsed = error.code === "not_authenticated" || error.code === "session_expired";
  // Only try a refresh if a session existed: every login sets the CSRF cookie. Without it,
  // a refresh can only fail (and would add a pointless 403 to the console).
  if (response.status === 401 && lapsed && retry && !NO_REFRESH.has(path) && csrfToken()) {
    await request("POST", "/auth/refresh", undefined, false); // throws if the session has ended
    return request<T>(method, path, body, false, timeoutMs, asFile);
  }
  throw error;
}

/** A file the server sent as an attachment (exports). */
export type Download = { blob: Blob; filename: string; rows: number | null };

async function toDownload(response: Response): Promise<Download> {
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "export";
  const rows = response.headers.get("X-Export-Rows");
  return { blob: await response.blob(), filename, rows: rows === null ? null : Number(rows) };
}

/** POST that returns a file; exports can take longer than a data query. */
export const EXPORT_TIMEOUT_MS = 60_000;
export const apiPostFile = (path: string, body: unknown) =>
  request<Download>("POST", path, body, true, EXPORT_TIMEOUT_MS, true);

export const apiGet = <T>(path: string) => request<T>("GET", path);
export const apiPost = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
export const apiPut = <T>(path: string, body?: unknown) => request<T>("PUT", path, body);
export const apiDelete = <T>(path: string) => request<T>("DELETE", path);

export const getHealth = () => apiGet<Health>("/health");
export const getMe = () => apiGet<User>("/me");
export const login = (email: string, password: string) =>
  apiPost<LoginResult>("/auth/login", { email, password });
export const logout = () => apiPost<{ ok: boolean }>("/auth/logout");
export const changePassword = (current_password: string, new_password: string) =>
  apiPost<LoginResult>("/auth/change-password", { current_password, new_password });
export const startMfaSetup = () => apiPost<MfaSetup>("/auth/mfa/setup");
/** The first successful code (enrolment) also returns the recovery codes, shown once (D-037). */
export type MfaVerifyResult = LoginResult & { recovery_codes?: string[] | null };
export type RecoveryLoginResult = LoginResult & { recovery_codes_remaining: number };
export type RecoveryStatus = { remaining: number; low: boolean };
export const verifyMfa = (code: string) => apiPost<MfaVerifyResult>("/auth/mfa/verify", { code });
export const signInWithRecoveryCode = (code: string) =>
  apiPost<RecoveryLoginResult>("/auth/mfa/recovery", { code });
export const getRecoveryStatus = () => apiGet<RecoveryStatus>("/auth/mfa/recovery-codes");
export const regenerateRecoveryCodes = () =>
  apiPost<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes");

/** Insights are computed on the server (then cached): allow longer than a dashboard query. */
export const ANALYSIS_TIMEOUT_MS = 15_000;
export const apiGetAnalysis = <T>(path: string) =>
  request<T>("GET", path, undefined, true, ANALYSIS_TIMEOUT_MS);

/** GET with the UC2 5-second timeout, for data endpoints. */
export const apiGetData = <T>(path: string) =>
  request<T>("GET", path, undefined, true, DATA_TIMEOUT_MS);
