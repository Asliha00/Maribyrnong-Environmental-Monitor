import { useState, type ReactNode } from "react";

/** A titled panel with a Chart / Table switch: every visualisation has a table view
 * (accessibility, and the relief the palette's light-mode contrast warning requires). */
export default function ChartFrame({
  id,
  title,
  subtitle,
  actions,
  chart,
  table,
}: {
  id: string;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  chart: ReactNode;
  table: ReactNode;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="rounded border border-slate-300 p-4 dark:border-slate-700"
    >
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={`${id}-title`} className="text-lg font-semibold">
            {title}
          </h2>
          {subtitle && <p className="text-sm text-slate-600 dark:text-slate-400">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">
          {actions}
          <div
            role="group"
            aria-label="View as"
            className="flex rounded border border-slate-400 text-sm"
          >
            {(["chart", "table"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className={`px-2 py-1 capitalize focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 ${
                  view === v
                    ? "bg-sky-800 text-white"
                    : "hover:bg-slate-100 dark:hover:bg-slate-800"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>
      {view === "chart" ? chart : <div className="max-h-96 overflow-auto">{table}</div>}
    </section>
  );
}
