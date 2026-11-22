import { useState } from "react";

/**
 * A device key or temporary password, shown exactly once. It lives only in component state
 * (never storage) and disappears when dismissed or when the page is left.
 */
export default function OneTimeSecret({
  label,
  value,
  note,
  onDismiss,
}: {
  label: string;
  value: string;
  note: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div
      role="region"
      aria-label={label}
      className="rounded border-2 border-amber-600 bg-amber-50 p-4 text-sm text-slate-900 dark:bg-amber-950 dark:text-amber-50"
    >
      <p className="font-semibold">{label}</p>
      <p className="mt-1">{note}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <code className="select-all break-all rounded bg-white px-2 py-1 font-mono text-base dark:bg-slate-900">
          {value}
        </code>
        <button
          type="button"
          className="rounded border border-slate-500 px-3 py-1"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value);
              setCopied(true);
            } catch {
              setCopied(false); // clipboard blocked: the value is selectable instead
            }
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <button
          type="button"
          className="rounded border border-slate-500 px-3 py-1"
          onClick={onDismiss}
        >
          I have saved it
        </button>
      </div>
    </div>
  );
}
