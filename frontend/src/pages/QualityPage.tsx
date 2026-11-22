import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { getMeta } from "../api/data";
import {
  getCompleteness,
  getErrors,
  getFlags,
  getRuns,
  getSecurityEvents,
  type Completeness,
} from "../api/admin";
import { ErrorMessage, Loading } from "../components/StatusMessage";
import { useAuth } from "../hooks/useAuth";
import { formatMelbourne } from "../lib/format";
import { rampColor, SEQUENTIAL } from "../lib/palette";

const PAGE = 25;
const ERROR_TYPES = [
  "out_of_range",
  "not_fitted",
  "duplicate",
  "invalid_timestamp",
  "unknown_sensor",
  "ingest_rejected",
];
const field = "mt-1 rounded border border-slate-400 px-2 py-1.5 text-sm dark:bg-slate-900";

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** One strip per sensor, one cell per day, coloured by completeness (light = low, dark = full). */
function Calendar({ data }: { data: Completeness }) {
  const days = data.sensors[0]?.cells.length ?? 0;
  const cell = Math.max(2, Math.min(10, Math.floor(720 / Math.max(days, 1))));
  return (
    <div className="space-y-2 overflow-x-auto">
      {data.sensors.map((s) => (
        <div key={s.sensor_id} className="flex items-center gap-3">
          <span className="w-24 shrink-0 text-sm font-medium">{s.sensor_code}</span>
          <svg
            width={days * cell}
            height={18}
            role="img"
            aria-label={`${s.sensor_code}: ${s.valid_days} of ${s.days} days at least ${data.min_valid_pct}% complete`}
          >
            {s.cells.map((c, i) => (
              <rect
                key={c.date}
                x={i * cell}
                y={0}
                width={Math.max(cell - (cell > 3 ? 1 : 0), 1)}
                height={18}
                fill={c.pct > 0 ? rampColor(c.pct, 0, 100) : "var(--chart-grid)"}
              >
                <title>{`${c.date}: ${c.pct}%${c.valid ? "" : " (below 75%)"}`}</title>
              </rect>
            ))}
          </svg>
        </div>
      ))}
      <div className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
        <span>No data</span>
        <span className="inline-block h-3 w-4" style={{ background: "var(--chart-grid)" }} />
        <span className="ml-2">0%</span>
        {SEQUENTIAL.map((c) => (
          <span key={c} className="inline-block h-3 w-3" style={{ background: c }} />
        ))}
        <span>100% of expected readings</span>
      </div>
    </div>
  );
}

/** Data-quality page (§4.5): analysts and administrators. */
export default function QualityPage() {
  const { user } = useAuth();
  const meta = useQuery({ queryKey: ["meta"], queryFn: getMeta, staleTime: 10 * 60_000 });
  const last = meta.data?.data_range.last_day ?? null;
  const [variable, setVariable] = useState("temperature_c");
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const span = useMemo(
    () => range ?? (last ? { start: shiftDays(last, -91), end: last } : null),
    [range, last],
  );
  const [errorFilters, setErrorFilters] = useState<{ error_type: string; sensor_id: string }>({
    error_type: "",
    sensor_id: "",
  });
  const [offset, setOffset] = useState(0);

  const completeness = useQuery({
    queryKey: ["quality", "completeness", variable, span],
    queryFn: () => getCompleteness(variable, span!.start, span!.end),
    enabled: !!span,
    placeholderData: keepPreviousData,
  });
  const errorParams = Object.fromEntries(
    Object.entries({ ...errorFilters, limit: String(PAGE), offset: String(offset) }).filter(
      ([, v]) => v !== "",
    ),
  );
  const errors = useQuery({
    queryKey: ["quality", "errors", errorParams],
    queryFn: () => getErrors(errorParams),
    placeholderData: keepPreviousData,
  });
  const runs = useQuery({ queryKey: ["quality", "runs"], queryFn: getRuns });
  const flags = useQuery({ queryKey: ["quality", "flags"], queryFn: getFlags });
  const isAdmin = !!user?.permissions.includes("manage_users");
  const security = useQuery({
    queryKey: ["quality", "security"],
    queryFn: getSecurityEvents,
    enabled: isAdmin,
  });

  if (meta.isPending) return <Loading label="Loading data quality…" />;
  if (meta.isError) return <ErrorMessage error={meta.error} onRetry={() => meta.refetch()} />;

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Data quality</h1>

      <section aria-labelledby="calendar-title" className="space-y-3">
        <h2 id="calendar-title" className="text-xl font-semibold">
          Completeness by day
        </h2>
        <p className="max-w-prose text-sm text-slate-700 dark:text-slate-300">
          Share of the expected readings each sensor sent on each day. Days below 75% are not used
          for threshold checks and are greyed out on the dashboard.
        </p>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => e.preventDefault()}>
          <label className="text-sm">
            Variable
            <select
              className={`${field} block`}
              value={variable}
              onChange={(e) => setVariable(e.target.value)}
            >
              {meta.data.variables.map((v) => (
                <option key={v.variable} value={v.variable}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            From
            <input
              type="date"
              className={`${field} block`}
              value={span?.start ?? ""}
              max={span?.end}
              onChange={(e) => span && setRange({ ...span, start: e.target.value })}
            />
          </label>
          <label className="text-sm">
            To
            <input
              type="date"
              className={`${field} block`}
              value={span?.end ?? ""}
              min={span?.start}
              onChange={(e) => span && setRange({ ...span, end: e.target.value })}
            />
          </label>
        </form>
        {completeness.isError ? (
          <ErrorMessage error={completeness.error} onRetry={() => completeness.refetch()} />
        ) : completeness.data ? (
          <>
            <Calendar data={completeness.data} />
            <table className="text-left text-sm">
              <caption className="sr-only">Completeness summary per sensor</caption>
              <thead className="border-b border-slate-400">
                <tr>
                  <th scope="col" className="py-1 pr-4">
                    Sensor
                  </th>
                  <th scope="col" className="pr-4">
                    Days at least 75% complete
                  </th>
                  <th scope="col" className="pr-4">
                    Average completeness
                  </th>
                </tr>
              </thead>
              <tbody>
                {completeness.data.sensors.map((s) => (
                  <tr key={s.sensor_id} className="border-b border-slate-200 dark:border-slate-800">
                    <th scope="row" className="py-1 pr-4 font-normal">
                      {s.sensor_code} · {s.sensor_name}
                      {s.status !== "Active" && " (decommissioned)"}
                    </th>
                    <td className="pr-4">
                      {s.valid_days} of {s.days}
                    </td>
                    <td className="pr-4">{s.avg_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <Loading label="Loading completeness…" />
        )}
      </section>

      <section aria-labelledby="errors-title" className="space-y-3">
        <h2 id="errors-title" className="text-xl font-semibold">
          Rejected values and file problems
        </h2>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => e.preventDefault()}>
          <label className="text-sm">
            Problem type
            <select
              className={`${field} block`}
              value={errorFilters.error_type}
              onChange={(e) => {
                setOffset(0);
                setErrorFilters({ ...errorFilters, error_type: e.target.value });
              }}
            >
              <option value="">All</option>
              {ERROR_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                  {errors.data?.by_type[t] !== undefined ? ` (${errors.data.by_type[t]})` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Sensor
            <select
              className={`${field} block`}
              value={errorFilters.sensor_id}
              onChange={(e) => {
                setOffset(0);
                setErrorFilters({ ...errorFilters, sensor_id: e.target.value });
              }}
            >
              <option value="">All</option>
              {(completeness.data?.sensors ?? []).map((s) => (
                <option key={s.sensor_id} value={s.sensor_id}>
                  {s.sensor_code}
                </option>
              ))}
            </select>
          </label>
        </form>
        {errors.isError ? (
          <ErrorMessage error={errors.error} onRetry={() => errors.refetch()} />
        ) : !errors.data ? (
          <Loading label="Loading problems…" />
        ) : errors.data.total === 0 ? (
          <p className="text-sm">No problems recorded for these filters.</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">
                  Rejected values and file problems, newest first
                </caption>
                <thead className="border-b border-slate-400">
                  <tr>
                    <th scope="col" className="py-1 pr-3">
                      Reading time
                    </th>
                    <th scope="col" className="pr-3">
                      Sensor
                    </th>
                    <th scope="col" className="pr-3">
                      Problem
                    </th>
                    <th scope="col" className="pr-3">
                      Variable
                    </th>
                    <th scope="col" className="pr-3">
                      Value
                    </th>
                    <th scope="col" className="pr-3">
                      Details
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {errors.data.items.map((e) => (
                    <tr
                      key={e.error_id}
                      className="border-b border-slate-200 align-top dark:border-slate-800"
                    >
                      <td className="py-1 pr-3 whitespace-nowrap">
                        {e.ts_utc ? formatMelbourne(e.ts_utc) : "—"}
                      </td>
                      <td className="pr-3">{e.sensor_code ?? "—"}</td>
                      <td className="pr-3">{e.error_type.replace(/_/g, " ")}</td>
                      <td className="pr-3">{e.variable ?? "—"}</td>
                      <td className="pr-3 break-all">{e.raw_value ?? "—"}</td>
                      <td className="pr-3">{e.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center gap-3 text-sm">
              <button
                type="button"
                className="rounded border border-slate-400 px-3 py-1 disabled:opacity-50"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Previous
              </button>
              <span>
                {offset + 1}–{Math.min(offset + PAGE, errors.data.total)} of {errors.data.total}
              </span>
              <button
                type="button"
                className="rounded border border-slate-400 px-3 py-1 disabled:opacity-50"
                disabled={offset + PAGE >= errors.data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </section>

      <section aria-labelledby="flags-title" className="space-y-3">
        <h2 id="flags-title" className="text-xl font-semibold">
          Flagged values (kept, marked)
        </h2>
        {flags.isError ? (
          <ErrorMessage error={flags.error} onRetry={() => flags.refetch()} />
        ) : !flags.data ? (
          <Loading />
        ) : (
          <table className="text-left text-sm">
            <caption className="sr-only">Flagged readings per sensor and flag</caption>
            <thead className="border-b border-slate-400">
              <tr>
                <th scope="col" className="py-1 pr-4">
                  Sensor
                </th>
                <th scope="col" className="pr-4">
                  Flag
                </th>
                <th scope="col" className="pr-4">
                  Readings
                </th>
              </tr>
            </thead>
            <tbody>
              {flags.data.items.map((f) => (
                <tr
                  key={`${f.sensor_code}-${f.flag}`}
                  className="border-b border-slate-200 dark:border-slate-800"
                >
                  <td className="py-1 pr-4">{f.sensor_code}</td>
                  <td className="pr-4">{f.description}</td>
                  <td className="pr-4">{f.readings.toLocaleString("en-AU")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="runs-title" className="space-y-3">
        <h2 id="runs-title" className="text-xl font-semibold">
          Files loaded
        </h2>
        {runs.isError ? (
          <ErrorMessage error={runs.error} onRetry={() => runs.refetch()} />
        ) : !runs.data ? (
          <Loading />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Ingestion runs, newest first</caption>
              <thead className="border-b border-slate-400">
                <tr>
                  <th scope="col" className="py-1 pr-3">
                    Started
                  </th>
                  <th scope="col" className="pr-3">
                    Sensor
                  </th>
                  <th scope="col" className="pr-3">
                    File
                  </th>
                  <th scope="col" className="pr-3">
                    Rows read
                  </th>
                  <th scope="col" className="pr-3">
                    New
                  </th>
                  <th scope="col" className="pr-3">
                    Rejected values
                  </th>
                  <th scope="col" className="pr-3">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((r) => (
                  <tr
                    key={r.run_id}
                    className="border-b border-slate-200 align-top dark:border-slate-800"
                  >
                    <td className="py-1 pr-3 whitespace-nowrap">{formatMelbourne(r.started_at)}</td>
                    <td className="pr-3">{r.sensor_code ?? "—"}</td>
                    <td className="pr-3 break-all">{r.source_file}</td>
                    <td className="pr-3">{r.rows_read?.toLocaleString("en-AU") ?? "—"}</td>
                    <td className="pr-3">{r.rows_inserted?.toLocaleString("en-AU") ?? "—"}</td>
                    <td className="pr-3">{r.values_rejected?.toLocaleString("en-AU") ?? "—"}</td>
                    <td className="pr-3">
                      {r.completed
                        ? r.archived
                          ? "Loaded, original archived"
                          : "Loaded"
                        : "Did not finish"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {isAdmin && (
        <section aria-labelledby="security-title" className="space-y-3">
          <h2 id="security-title" className="text-xl font-semibold">
            Suspicious login activity
          </h2>
          <p className="max-w-prose text-sm text-slate-700 dark:text-slate-300">
            Recorded when there are more than 20 failed logins within 10 minutes (administrators
            only).
          </p>
          {security.isError ? (
            <ErrorMessage error={security.error} />
          ) : !security.data ? (
            <Loading />
          ) : security.data.items.length === 0 ? (
            <p className="text-sm">None recorded.</p>
          ) : (
            <ul className="list-disc pl-6 text-sm">
              {security.data.items.map((s) => (
                <li key={s.audit_id}>
                  {formatMelbourne(s.created_at)}: {s.failed_logins_last_10_min} failed logins in 10
                  minutes
                  {s.ip_address ? ` (last from ${s.ip_address})` : ""}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
