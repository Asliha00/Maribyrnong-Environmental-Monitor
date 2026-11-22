/**
 * POST /api/blob-upload (BUILD_PROMPT §4.5 step 2). BUILD_PROMPT names this test
 * `test_blob_upload.py::test_non_admin_cannot_get_upload_token`; the route is Node, so it is
 * tested here with Vitest. The Blob SDK is mocked: the tests check who gets a token and with
 * which constraints, not Vercel's signing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const issued: unknown[] = [];
vi.mock("@vercel/blob", () => ({
  issueSignedToken: vi.fn(async (options: unknown) => {
    issued.push(options);
    return { clientSigningToken: "signing", delegationToken: "delegation" };
  }),
}));
vi.mock("@vercel/blob/client", () => ({
  // Stand-in for the SDK helper: ask our getSignedToken, return what it produced
  handleUploadPresigned: vi.fn(
    async ({ body, getSignedToken }: { body: { payload: { pathname: string } }; getSignedToken: Function }) => ({
      type: "blob.generate-presigned-url",
      presignedUrlPayload: await getSignedToken(body.payload.pathname, null, false),
    }),
  ),
}));

const { app } = await import("../src/index.js");
const { MAX_UPLOAD_BYTES, uploadConstraints } = await import("../src/policy.js");

const GOOD = "uploads/mcc-1-export-0123456789abcdef0123456789abcdef.csv";
let checkStatus: number;
let checkCalls: { url: string; cookie: string }[];

beforeEach(() => {
  issued.length = 0;
  checkStatus = 200;
  checkCalls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: URL, init: RequestInit) => {
      checkCalls.push({ url: String(url), cookie: (init.headers as Record<string, string>).cookie });
      return new Response(null, { status: checkStatus });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function request(pathname = GOOD, opts: { csrf?: string; cookie?: string; type?: string } = {}) {
  const csrf = opts.csrf ?? "tok";
  return app.request("/api/blob-upload", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      cookie: opts.cookie ?? "mem_access=access.jwt; mem_csrf=tok; other=x",
      "x-csrf-token": csrf,
    },
    body: JSON.stringify({
      type: opts.type ?? "blob.generate-presigned-url",
      payload: { pathname, multipart: false, clientPayload: null },
    }),
  });
}

describe("who gets an upload token", () => {
  it("non-admin cannot get upload token", async () => {
    checkStatus = 403; // FastAPI says: no manage_sensors (or admin without MFA)
    const response = await request();
    expect(response.status).toBe(403);
    expect(issued).toEqual([]);
  });

  it("anonymous (no access cookie) is refused without asking the backend", async () => {
    const response = await request(GOOD, { cookie: "mem_csrf=tok" });
    expect(response.status).toBe(403);
    expect(checkCalls).toEqual([]);
    expect(issued).toEqual([]);
  });

  it("missing or mismatched CSRF token is refused", async () => {
    expect((await request(GOOD, { csrf: "" })).status).toBe(403);
    expect((await request(GOOD, { csrf: "other" })).status).toBe(403);
    expect(checkCalls).toEqual([]);
  });

  it("backend unreachable means no token", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    expect((await request()).status).toBe(403);
    expect(issued).toEqual([]);
  });

  it("an administrator gets a CSV-only, 50 MB, short-lived token for that one pathname", async () => {
    const before = Date.now();
    const response = await request();
    expect(response.status).toBe(200);
    expect(checkCalls).toEqual([
      { url: "http://127.0.0.1:8000/api/auth/check?permission=manage_sensors", cookie: "mem_access=access.jwt" },
    ]); // only the access cookie is forwarded
    expect(issued).toHaveLength(1);
    const options = issued[0] as Record<string, unknown>;
    expect(options).toMatchObject({
      pathname: GOOD,
      operations: ["put"],
      allowedContentTypes: ["text/csv"],
      maximumSizeInBytes: 50 * 1024 * 1024,
    });
    expect(options.validUntil as number).toBeLessThanOrEqual(before + 10 * 60 * 1000 + 1000);
    const body = (await response.json()) as { presignedUrlPayload: { urlOptions: Record<string, unknown> } };
    expect(body.presignedUrlPayload.urlOptions).toMatchObject({ allowOverwrite: false });
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
});

describe("what may be uploaded", () => {
  it.each([
    "uploads/../raw/x-0123456789abcdef0123456789abcdef.csv",
    "raw/abc__x.csv",
    "uploads/x.csv", // no random part
    "uploads/a/b-0123456789abcdef0123456789abcdef.csv",
    "uploads/x-0123456789abcdef0123456789abcdef.exe",
    "uploads/x-0123456789abcdef0123456789abcdef.csv.exe",
    "uploads/.x-0123456789abcdef0123456789abcdef.csv",
    "uploads/x-0123456789ABCDEF0123456789ABCDEF.csv",
  ])("refuses the pathname %s", async (pathname) => {
    expect(uploadConstraints(pathname)).toBeNull();
    expect((await request(pathname)).status).toBe(400);
    expect(issued).toEqual([]);
  });

  it("refuses upload-completed callbacks (none are configured)", async () => {
    expect((await request(GOOD, { type: "blob.upload-completed" })).status).toBe(400);
  });

  it("limits match SEC-20", () => {
    expect(MAX_UPLOAD_BYTES).toBe(52_428_800);
  });

  it("other paths and methods are 404", async () => {
    expect((await app.request("/api/blob-upload")).status).toBe(404);
    expect((await app.request("/api/anything", { method: "POST" })).status).toBe(404);
  });
});

describe("when the Blob store is not set up for this deployment", () => {
  it("answers 503 with a plain message and logs the reason", async () => {
    const { issueSignedToken } = await import("@vercel/blob");
    vi.mocked(issueSignedToken).mockRejectedValueOnce(new Error("BLOB_STORE_ID is required"));
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const response = await request();
    expect(response.status).toBe(503);
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe("upload_unavailable");
    expect(String(log.mock.calls[0])).toContain("BLOB_STORE_ID is required");
    log.mockRestore();
  });
});
