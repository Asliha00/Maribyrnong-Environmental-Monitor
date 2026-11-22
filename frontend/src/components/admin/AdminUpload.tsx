import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, csrfToken } from "../../api/client";
import { ingestUpload, listAdminSensors, type UploadSummary } from "../../api/admin";
import { ErrorMessage, Loading } from "../StatusMessage";

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
/** The browser-to-store step failed: refused token, store unavailable, or connection lost. */
export const UPLOAD_FAILED =
  "The file could not be uploaded. Please try again. If it keeps failing, contact your system administrator.";
const MULTIPART_FROM_BYTES = 8 * 1024 * 1024;

/** uploads/<safe name>-<32 hex random>.csv: the only form the token route accepts (SEC-20). */
export function uploadPathname(
  fileName: string,
  random: Uint8Array = crypto.getRandomValues(new Uint8Array(16)),
) {
  const base =
    fileName
      .replace(/\.csv$/i, "")
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^[^A-Za-z0-9]+/, "")
      .replace(/[-.]+$/, "")
      .slice(0, 80) || "upload";
  const hex = Array.from(random, (b) => b.toString(16).padStart(2, "0")).join("");
  return `uploads/${base}-${hex}.csv`;
}

/** Client-side checks; the server repeats them (and more) after the upload. */
export function fileProblem(file: File | null): string | null {
  if (!file) return "Choose a CSV file.";
  if (!/\.csv$/i.test(file.name))
    return "Choose a CSV file (.csv). Export spreadsheets as CSV first.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES)
    return "The file is larger than 50 MB. Split it into smaller files.";
  return null;
}

type Phase =
  | { kind: "idle" }
  | { kind: "uploading"; percent: number }
  | { kind: "processing" }
  | { kind: "done"; summary: UploadSummary; message: string }
  | { kind: "error"; error: unknown };

const field = "mt-1 w-full rounded border border-slate-400 px-2 py-1.5 text-sm dark:bg-slate-900";

/**
 * Admin CSV upload (§4.5): the browser sends the file straight to the PRIVATE Blob store with a
 * short-lived token from /api/blob-upload (Vercel functions cannot receive bodies over 4.5 MB),
 * then asks FastAPI to check, archive and load it.
 */
export default function AdminUpload() {
  const qc = useQueryClient();
  const sensors = useQuery({ queryKey: ["admin", "sensors"], queryFn: listAdminSensors });
  const [sensorId, setSensorId] = useState<number | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [force, setForce] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [checked, setChecked] = useState(false);
  const busy = phase.kind === "uploading" || phase.kind === "processing";

  async function start() {
    setChecked(true);
    if (fileProblem(file) || sensorId === "") return;
    const chosen = file as File;
    const pathname = uploadPathname(chosen.name);
    setPhase({ kind: "uploading", percent: 0 });
    try {
      const { uploadPresigned } = await import("@vercel/blob/client"); // loaded only on this page
      await uploadPresigned(pathname, chosen, {
        access: "private",
        handleUploadUrl: "/api/blob-upload",
        headers: { "X-CSRF-Token": csrfToken() },
        contentType: "text/csv",
        multipart: chosen.size >= MULTIPART_FROM_BYTES,
        onUploadProgress: ({ percentage }) =>
          setPhase({ kind: "uploading", percent: Math.round(percentage) }),
      });
    } catch {
      // token refused or connection lost: the server sends nothing more specific we can show
      setPhase({
        kind: "error",
        error: new ApiError(0, "upload_failed", UPLOAD_FAILED),
      });
      return;
    }
    setPhase({ kind: "processing" });
    try {
      const r = await ingestUpload(pathname, sensorId, force);
      setPhase({ kind: "done", summary: r.summary, message: r.message });
      qc.invalidateQueries(); // new readings: refresh the dashboard and quality pages
    } catch (error) {
      setPhase({ kind: "error", error });
    }
  }

  if (sensors.isPending) return <Loading label="Loading sensors…" />;
  if (sensors.isError)
    return <ErrorMessage error={sensors.error} onRetry={() => sensors.refetch()} />;
  const active = sensors.data.sensors.filter((s) => s.status === "Active");
  const problem = checked
    ? (fileProblem(file) ?? (sensorId === "" ? "Choose the sensor this file belongs to." : null))
    : null;

  return (
    <section aria-labelledby="upload-title" className="max-w-2xl space-y-4">
      <h2 id="upload-title" className="text-xl font-semibold">
        Upload sensor data (CSV)
      </h2>
      <p className="text-sm text-slate-700 dark:text-slate-300">
        Upload a council export (Ubidots CSV) for one sensor. The file is checked against that
        sensor's device type, the original is archived privately, new readings are added (duplicates
        are skipped) and the sensor's hourly, daily and monthly figures are recalculated. Large
        files can take a minute.
      </p>
      <form
        noValidate
        aria-label="Upload sensor data"
        className="grid gap-3 rounded border border-slate-300 p-4 dark:border-slate-700"
        onSubmit={(e) => {
          e.preventDefault();
          void start();
        }}
      >
        <label className="text-sm">
          Sensor
          <select
            className={field}
            value={sensorId}
            disabled={busy}
            aria-invalid={checked && sensorId === ""}
            onChange={(e) => setSensorId(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">Choose the sensor this file belongs to</option>
            {active.map((s) => (
              <option key={s.sensor_id} value={s.sensor_id}>
                {s.sensor_code} · {s.sensor_name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          CSV file (up to 50 MB)
          <input
            type="file"
            accept=".csv,text/csv"
            className="mt-1 block text-sm"
            disabled={busy}
            aria-invalid={!!problem}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setPhase({ kind: "idle" });
            }}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={force}
            disabled={busy}
            onChange={(e) => setForce(e.target.checked)}
          />
          Load again if this exact file was loaded before (readings already stored are skipped)
        </label>
        {problem && (
          <p role="alert" className="text-sm text-red-800 dark:text-red-300">
            {problem}
          </p>
        )}
        <div>
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-60"
          >
            Upload and load
          </button>
        </div>
      </form>

      {phase.kind === "uploading" && (
        <div role="status">
          <p className="text-sm">Uploading… {phase.percent}%</p>
          <progress
            className="w-full"
            max={100}
            value={phase.percent}
            aria-label="Upload progress"
          />
        </div>
      )}
      {phase.kind === "processing" && (
        <p role="status" className="text-sm">
          Checking and loading the file. This can take up to a few minutes for large files; please
          keep this page open.
        </p>
      )}
      {phase.kind === "error" && <ErrorMessage error={phase.error} />}
      {phase.kind === "done" && (
        <div role="status" className="rounded border border-emerald-700 p-4 text-sm">
          <p className="font-semibold">{phase.message}</p>
          <dl className="mt-2 grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-1">
            {(
              [
                ["Rows read", phase.summary.rows_read],
                ["New readings added", phase.summary.rows_inserted],
                ["Already in the database (skipped)", phase.summary.rows_already_stored],
                ["Repeated rows in the file (skipped)", phase.summary.rows_duplicate],
                ["Values rejected (out of range)", phase.summary.values_rejected],
                ["Values flagged (kept)", phase.summary.values_flagged],
              ] as const
            ).map(([label, n]) => (
              <div key={label} className="contents">
                <dt>{label}</dt>
                <dd className="text-right tabular-nums">{n.toLocaleString("en-AU")}</dd>
              </div>
            ))}
            <dt>Time taken</dt>
            <dd className="text-right tabular-nums">{phase.summary.seconds_total} s</dd>
          </dl>
          <p className="mt-2">Rejected values and flags are listed on the Data quality page.</p>
        </div>
      )}
    </section>
  );
}
