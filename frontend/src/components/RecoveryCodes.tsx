import { useId, useState } from "react";
import { saveDownload } from "./ExportControl";

export const SAVE_WARNING =
  "Save these codes somewhere safe, such as a password manager. Each one works once, in place of the 6-digit code. They will not be shown again.";

/** A new set of 2FA recovery codes, shown once (D-037). Continue is enabled only after the
 * user confirms they saved them. The codes live only in this component's state. */
export default function RecoveryCodes({
  codes,
  onDone,
  doneLabel = "Continue",
}: {
  codes: string[];
  onDone: () => void;
  doneLabel?: string;
}) {
  const [saved, setSaved] = useState(false);
  const [status, setStatus] = useState("");
  const checkId = useId();
  const text = codes.join("\n");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setStatus("Codes copied.");
    } catch {
      setStatus("Could not copy. Select the codes and copy them, or download them instead.");
    }
  }

  function download() {
    const body = `Maribyrnong Environmental Monitor - 2FA recovery codes\nEach code works once.\n\n${text}\n`;
    saveDownload({
      blob: new Blob([body], { type: "text/plain" }),
      filename: "maribyrnong-recovery-codes.txt",
      rows: null,
    });
    setStatus("Codes downloaded.");
  }

  return (
    <section aria-labelledby="recovery-title" className="mt-4 space-y-3">
      <h2 id="recovery-title" className="text-lg font-semibold">
        Your recovery codes
      </h2>
      <p className="text-sm text-slate-700 dark:text-slate-300">{SAVE_WARNING}</p>
      <ol
        aria-label="Recovery codes"
        className="grid grid-cols-2 gap-x-6 gap-y-1 rounded border border-slate-300 bg-slate-50 p-3 font-mono text-sm dark:border-slate-600 dark:bg-slate-800"
      >
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={copy}
          className="rounded border border-slate-400 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:hover:bg-slate-800"
        >
          Copy
        </button>
        <button
          type="button"
          onClick={download}
          className="rounded border border-slate-400 px-3 py-1.5 text-sm font-medium hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:hover:bg-slate-800"
        >
          Download
        </button>
      </div>
      <p aria-live="polite" className="text-sm">
        {status}
      </p>
      <div className="flex items-center gap-2">
        <input
          id={checkId}
          type="checkbox"
          checked={saved}
          onChange={(e) => setSaved(e.target.checked)}
          className="h-4 w-4"
        />
        <label htmlFor={checkId} className="text-sm">
          I have saved these codes
        </label>
      </div>
      <button
        type="button"
        onClick={onDone}
        disabled={!saved}
        className="rounded bg-sky-800 px-4 py-2 font-medium text-white hover:bg-sky-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 disabled:opacity-50"
      >
        {doneLabel}
      </button>
    </section>
  );
}
