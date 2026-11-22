/**
 * Who may upload, and what (BUILD_PROMPT §4.5 step 2; SEC-15, SEC-20). Kept free of the
 * Vercel SDK so it can be tested on its own.
 */

/** CSV only, 50 MB at most, server-checked pathname, short-lived, never overwrite. */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
export const ALLOWED_CONTENT_TYPES = ["text/csv"];
export const TOKEN_LIFETIME_MS = 10 * 60 * 1000;
/** uploads/<safe name>-<32 hex random>.csv: no directories, no "..", random part from the browser's crypto. */
export const UPLOAD_PATHNAME = /^uploads\/[A-Za-z0-9][A-Za-z0-9._-]{0,100}-[0-9a-f]{32}\.csv$/;
export const MAX_BODY_BYTES = 16 * 1024;

function cookie(header: string | null, name: string): string {
  for (const part of (header ?? "").split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return value.join("=");
  }
  return "";
}

/** Double-submit CSRF check, the same rule as the FastAPI backend (SEC-09). */
export function csrfOk(request: Request): boolean {
  const fromCookie = cookie(request.headers.get("cookie"), "mem_csrf");
  const fromHeader = request.headers.get("x-csrf-token") ?? "";
  return fromCookie.length > 0 && fromCookie === fromHeader;
}

/**
 * Ask the FastAPI backend whether this session holds manage_sensors (admin + MFA).
 * Only the access-token cookie is forwarded; anything but HTTP 200 means no.
 */
export async function isAdmin(
  request: Request,
  apiBaseUrl: string,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  const access = cookie(request.headers.get("cookie"), "mem_access");
  if (!access) return false;
  try {
    const response = await fetchImpl(
      new URL("/api/auth/check?permission=manage_sensors", apiBaseUrl),
      { headers: { cookie: `mem_access=${access}` }, redirect: "manual" },
    );
    return response.status === 200;
  } catch {
    return false; // backend unreachable: refuse
  }
}

/** Token constraints for one upload, or a refusal for a pathname we did not expect. */
export function uploadConstraints(pathname: string, now = Date.now()) {
  if (!UPLOAD_PATHNAME.test(pathname) || pathname.includes("..")) return null;
  return {
    pathname,
    operations: ["put" as const],
    allowedContentTypes: ALLOWED_CONTENT_TYPES,
    maximumSizeInBytes: MAX_UPLOAD_BYTES,
    validUntil: now + TOKEN_LIFETIME_MS,
  };
}
