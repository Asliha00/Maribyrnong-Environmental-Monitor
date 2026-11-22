import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getExceedances, type Filters } from "../api/data";
import { formatBucket, formatNumber } from "../lib/format";
import InfoTip, { GLOSSARY } from "./InfoTip";
import { ErrorMessage, Loading } from "./StatusMessage";

type Sort = "date" | "value" | "sensor";

/** UC2 visualisation 4: exceedance days for the filtered period, sortable, with a count
 * badge. Status colour always comes with an icon and words, never colour alone. */
export default function AlertsPanel({ filters }: { filters: Filters }) {
  const [sort, setSort] = useState<Sort>("date");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [onlyVariable, setOnlyVariable] = useState(false);
  const query = useQuery({
    queryKey: [
      "exceedances",
      filters.start,
      filters.end,
      filters.landUses,
      filters.sensorIds,
      onlyVariable ? filters.variable : "",
      sort,
      order,
    ],
    queryFn: () =>
      getExceedances(
        { ...filters, variable: onlyVariable ? filters.variable : undefined },
        sort,
        order,
      ),
  });

  function sortBy(column: Sort) {
    if (column === sort) setOrder(order === "asc" ? "desc" : "asc");
    else {
      setSort(column);
      setOrder(column === "sensor" ? "asc" : "desc");
    }
  }

  const header = (column: Sort, label: string) => (
    <th
      scope="col"
      aria-sort={sort === column ? (order === "asc" ? "ascending" : "descending") : "none"}
      className="py-1 pr-2 text-left"
    >
      <button
        type="button"
        onClick={() => sortBy(column)}
        className="font-medium underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600"
      >
        {label}
        {sort === column ? (order === "asc" ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );

  const total = query.data?.total ?? 0;
  return (
    <section
      aria-labelledby="alerts-title"
      className="rounded border border-slate-300 p-4 dark:border-slate-700"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 id="alerts-title" className="flex items-center gap-2 text-lg font-semibold">
          Threshold alerts
          <span
            className={`rounded-full px-2 py-0.5 text-sm ${total ? "text-white" : "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100"}`}
            style={total ? { background: "var(--status-critical)" } : undefined}
            aria-label={`${total} exceedance day${total === 1 ? "" : "s"}`}
          >
            {query.isPending ? "…" : total}
          </span>
          <InfoTip label="the NEPM standard" text={GLOSSARY.nepm} />
        </h2>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={onlyVariable}
            onChange={(e) => setOnlyVariable(e.target.checked)}
          />
          Only the selected variable
        </label>
      </div>
      <p className="mb-2 text-xs text-slate-600 dark:text-slate-400">
        Days in the filtered period when a valid daily figure passed a standard or heat trigger.
      </p>
      {query.isPending && <Loading label="Loading alerts…" />}
      {query.isError && <ErrorMessage error={query.error} onRetry={() => query.refetch()} />}
      {query.data && total === 0 && (
        <p role="status" className="text-sm">
          No exceedance days for these filters.
        </p>
      )}
      {query.data && total > 0 && (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {header("date", "Date")}
                {header("sensor", "Sensor")}
                <th scope="col" className="py-1 pr-2 text-left">
                  Alert
                </th>
                {header("value", "Value")}
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((e) => (
                <tr
                  key={`${e.date_local}-${e.sensor_id}-${e.threshold_id}`}
                  className="border-t border-slate-200 dark:border-slate-800"
                >
                  <td className="py-1 pr-2">{formatBucket(e.date_local)}</td>
                  <td className="py-1 pr-2">
                    <span className="font-medium">{e.sensor_code}</span>{" "}
                    <span className="text-slate-600 dark:text-slate-400">{e.land_use}</span>
                  </td>
                  <td className="py-1 pr-2">
                    <span aria-hidden="true" style={{ color: "var(--status-critical)" }}>
                      ▲{" "}
                    </span>
                    {e.label}
                  </td>
                  <td className="py-1 pr-2 tabular-nums">
                    {formatNumber(e.observed_value, e.variable)} {e.unit}
                    <span className="text-slate-600 dark:text-slate-400">
                      {" "}
                      ({e.statistic}, limit {e.operator}{" "}
                      {formatNumber(e.threshold_value, e.variable)})
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
