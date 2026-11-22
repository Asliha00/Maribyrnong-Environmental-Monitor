/**
 * POST /api/blob-upload: issues a presigned, private Vercel Blob upload URL so an administrator's
 * browser can send a council CSV (2–21 MB) straight to the Blob store. Vercel functions cannot
 * receive request bodies over 4.5 MB, so the file never passes through FastAPI on the way in.
 *
 * The presigned flow works with Vercel OIDC (no long-lived Blob token on the server). The
 * permission check is delegated to FastAPI (GET /api/auth/check?permission=manage_sensors)
 * through a private service binding, so there is one source of truth for who is an admin.
 */
import { issueSignedToken } from "@vercel/blob";
import { handleUploadPresigned, type HandleUploadPresignedBody } from "@vercel/blob/client";
import { Hono } from "hono";
import { csrfOk, isAdmin, MAX_BODY_BYTES, uploadConstraints } from "./policy.js";

/** FastAPI's internal URL: the service binding on Vercel, uvicorn locally. */
const apiBaseUrl = () => process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const json = (status: number, message: string, code: string) =>
  Response.json({ error: { code, message } }, { status, headers: { "Cache-Control": "no-store" } });

export const app = new Hono();

app.post("/api/blob-upload", async (c) => {
  const request = c.req.raw;
  if (!csrfOk(request))
    return json(403, "Your request could not be verified. Please refresh the page and try again.", "csrf_failed");
  if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY_BYTES)
    return json(413, "Request too large.", "too_large");
  if (!(await isAdmin(request, apiBaseUrl())))
    return json(403, "You do not have permission to upload files.", "forbidden");

  let body: HandleUploadPresignedBody;
  try {
    body = (await request.json()) as HandleUploadPresignedBody;
  } catch {
    return json(400, "Invalid request.", "bad_request");
  }
  // Only token requests: no upload-completed callbacks are configured, so refuse them
  if (body?.type !== "blob.generate-presigned-url")
    return json(400, "Invalid request.", "bad_request");

  const constraints = uploadConstraints(body.payload?.pathname ?? "");
  if (!constraints)
    return json(400, "This file cannot be uploaded. Choose a CSV file and try again.", "upload_refused");
  try {
    const result = await handleUploadPresigned({
      body,
      request,
      getSignedToken: async () => ({
        token: await issueSignedToken(constraints),
        urlOptions: {
          allowedContentTypes: constraints.allowedContentTypes,
          maximumSizeInBytes: constraints.maximumSizeInBytes,
          validUntil: constraints.validUntil,
          allowOverwrite: false,
          addRandomSuffix: false, // the pathname already ends in 128 random bits (checked above)
        },
      }),
    });
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    // The Blob store refused or is not configured for this environment (e.g. no BLOB_STORE_ID
    // or no OIDC access). Log the reason for operators; it contains no secrets.
    console.error("blob-upload: could not issue an upload token:", (error as Error)?.message ?? error);
    return json(
      503,
      "File uploads are not available on this deployment right now. Please contact your administrator.",
      "upload_unavailable",
    );
  }
});

app.all("*", () => json(404, "Not found.", "not_found"));

export default app;
