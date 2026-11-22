import { useEffect, useId, useRef, useState } from "react";
import { ApiError, type Download } from "../api/client";
import { exportReport, type ExportFormat, type Filters } from "../api/data";

/** UC3 wording (BUILD_PROMPT §4.4). */
export const EXPORT_DISABLED_TIP = "Please apply a filter before exporting.";
export const EXPORT_READY = "Your export is ready.";
export const EXPORT_FAILED = "Export failed. Please try again or contact your administrator.";

/** Save a file the server sent, without it ever touching storage or the page's state. */
export function saveDownload({ blob, filename }: Download): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Server messages that tell the user what to change are shown as-is; anything else
 * (server error, timeout, lost connection) gets the UC3 failure message. */
function exportErrorMessage(error: unknown): string {
  if (
    error instanceof ApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 409
  )
    return error.message;
  return EXPORT_FAILED;
}

type Phase =
  | { kind: "choose" }
  | { kind: "working" }
  | { kind: "confirm-large"; message: string }
  | { kind: "error"; message: string };

const FORMATS: { value: ExportFormat; label: string; hint: string }[] = [
  {
    value: "csv",
    label: "CSV (spreadsheet)",
    hint: "Every filtered row, with units in the column headers and a block describing the filters.",
  },
  {
    value: "pdf",
    label: "PDF report",
    hint: "Summary table, chart, threshold exceedances and data-quality notes.",
  },
];

/**
 * Export button (disabled with a tooltip until the user has applied a filter) and the
 * format dialog: CSV or PDF, the >50,000-row warning, and the UC3 success/failure messages.
 */
export default function ExportControl({
  filters,
  applied,
}: {
  filters: Filters;
  applied: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [phase, setPhase] = useState<Phase>({ kind: "choose" });
  const [done, setDone] = useState(false);
  const [hover, setHover] = useState(false);
  const tipId = useId();
  const titleId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const firstOption = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) firstOption.current?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    setPhase({ kind: "choose" });
    button.current?.focus();
  }

  async function run(confirmLarge: boolean) {
    setPhase({ kind: "working" });
    try {
      saveDownload(await exportReport(filters, format, confirmLarge));
      setOpen(false);
      setPhase({ kind: "choose" });
      setDone(true);
      button.current?.focus();
    } catch (error) {
      if (error instanceof ApiError && error.code === "large_export")
        setPhase({ kind: "confirm-large", message: error.message });
      else setPhase({ kind: "error", message: exportErrorMessage(error) });
    }
  }

  const working = phase.kind === "working";
  return (
    <div className="flex flex-col items-end gap-1">
      <span className="relative inline-block">
        <button
          ref={button}
          type="button"
          aria-disabled={!applied}
          aria-describedby={applied ? undefined : tipId}
          onClick={() => {
            if (!applied) return;
            setDone(false);
            setOpen(true);
          }}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
          onFocus={() => setHover(true)}
          onBlur={() => setHover(false)}
          className={
            "rounded px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 " +
            (applied
              ? "bg-sky-700 text-white hover:bg-sky-800"
              : "cursor-not-allowed bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400")
          }
        >
          Export
        </button>
        {!applied && (
          <span
            id={tipId}
            role="tooltip"
            className={
              (hover ? "" : "hidden ") +
              "absolute right-0 top-11 z-[1000] w-60 rounded border border-slate-300 bg-white p-2 text-sm text-slate-800 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            }
          >
            {EXPORT_DISABLED_TIP}
          </span>
        )}
      </span>
      <p role="status" className="text-sm text-emerald-800 dark:text-emerald-300">
        {done ? EXPORT_READY : ""}
      </p>

      {open && (
        <div
          className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/40 p-4"
          onKeyDown={(e) => e.key === "Escape" && !working && close()}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className="w-full max-w-md rounded border border-slate-300 bg-white p-5 text-slate-900 shadow-xl dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          >
            <h2 id={titleId} className="text-lg font-semibold">
              Export data
            </h2>
            {phase.kind === "confirm-large" ? (
              <>
                <p role="alert" className="mt-3 text-sm">
                  {phase.message}
                </p>
                <div className="mt-5 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={close}
                    className="rounded border border-slate-400 px-4 py-2 text-sm"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    autoFocus
                    onClick={() => run(true)}
                    className="rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800"
                  >
                    Continue
                  </button>
                </div>
              </>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run(false);
                }}
              >
                <fieldset className="mt-3 space-y-3" disabled={working}>
                  <legend className="text-sm text-slate-700 dark:text-slate-300">
                    Choose a format for the applied filters.
                  </legend>
                  {FORMATS.map((f, i) => (
                    <label key={f.value} className="flex gap-2 text-sm">
                      <input
                        ref={i === 0 ? firstOption : undefined}
                        type="radio"
                        name="export-format"
                        value={f.value}
                        checked={format === f.value}
                        onChange={() => setFormat(f.value)}
                        className="mt-1"
                      />
                      <span>
                        <span className="font-medium">{f.label}</span>
                        <span className="block text-slate-600 dark:text-slate-400">{f.hint}</span>
                      </span>
                    </label>
                  ))}
                </fieldset>
                {working && (
                  <p role="status" className="mt-3 text-sm">
                    Preparing your export…
                  </p>
                )}
                {phase.kind === "error" && (
                  <p role="alert" className="mt-3 text-sm text-red-800 dark:text-red-300">
                    {phase.message}
                  </p>
                )}
                <div className="mt-5 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={close}
                    disabled={working}
                    className="rounded border border-slate-400 px-4 py-2 text-sm"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={working}
                    className="rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-60"
                  >
                    Download
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
