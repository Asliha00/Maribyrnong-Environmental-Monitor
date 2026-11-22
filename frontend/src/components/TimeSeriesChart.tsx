import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReadingsResult } from "../api/data";
import { mergeSeries, thresholdsToDraw } from "../lib/chart";
import { formatBucket, formatNumber, formatValue } from "../lib/format";
import { seriesColor } from "../lib/palette";
import ChartFrame from "./ChartFrame";
import InfoTip, { GLOSSARY } from "./InfoTip";

const TABLE_ROW_LIMIT = 500;

/**
 * UC2 visualisation 1: one line per sensor (colour fixed per sensor), threshold reference
 * lines where they apply, and buckets below 75% completeness drawn as grey dashed segments.
 */
export default function TimeSeriesChart({
  result,
  slots,
}: {
  result: ReadingsResult;
  slots: Record<string, number>;
}) {
  const { rows, points } = mergeSeries(result.series);
  const thresholds = thresholdsToDraw(result.thresholds, result.resolution);
  // Markers only for short series: dense dots on a 2px line read as a dashed line, which
  // would be confused with the dashed 'below 75% complete' segments.
  const many = rows.length > 16;
  const codes = result.series.map((s) => s.sensor_code);
  const fmt = (v: number | null | undefined) => formatValue(v, result.unit, result.variable);

  function TooltipBody({ active, label }: { active?: boolean; label?: string | number }) {
    if (!active || label === undefined) return null;
    return (
      <div className="rounded border border-slate-300 bg-white p-2 text-xs text-slate-900 shadow dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100">
        <p className="mb-1 font-medium">{formatBucket(String(label))}</p>
        <ul>
          {codes.map((code) => {
            const p = points[code][String(label)];
            return (
              <li key={code} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="inline-block h-2 w-3 rounded-sm"
                  style={{ background: seriesColor(slots[code] ?? 0) }}
                />
                <span className="w-16">{code}</span>
                <span className="tabular-nums">{p ? fmt(p.mean) : "No data"}</span>
                {p && p.completeness_pct !== null && (
                  <span className={p.valid ? "text-slate-500" : "font-medium text-amber-700"}>
                    {formatNumber(p.completeness_pct)}% complete{p.valid ? "" : " (below 75%)"}
                  </span>
                )}
                {p?.flagged && <span className="font-medium text-amber-700">flagged</span>}
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  const chart = (
    <div>
      <div className="h-80 w-full" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis
              dataKey="t"
              tickFormatter={formatBucket}
              stroke="var(--chart-axis)"
              tick={{ fill: "var(--chart-muted)", fontSize: 12 }}
              minTickGap={24}
            />
            <YAxis
              stroke="var(--chart-axis)"
              tick={{ fill: "var(--chart-muted)", fontSize: 12 }}
              width={56}
              label={{
                value: result.unit,
                angle: -90,
                position: "insideLeft",
                fill: "var(--chart-muted)",
                fontSize: 12,
              }}
              domain={["auto", "auto"]}
            />
            <Tooltip
              content={(p) => <TooltipBody active={p.active} label={p.label} />}
              cursor={{ stroke: "var(--chart-axis)" }}
            />
            {thresholds.map((t) => (
              <ReferenceLine
                key={t.threshold_id}
                y={t.value}
                stroke="var(--chart-ink-2)"
                strokeDasharray="6 4"
                label={{
                  value: `${t.label} (${formatValue(t.value, result.unit, result.variable)})`,
                  position: "insideTopRight",
                  fill: "var(--chart-ink-2)",
                  fontSize: 12,
                }}
              />
            ))}
            {codes.map((code) => (
              <Line
                key={`${code}-invalid`}
                dataKey={`${code}__invalid`}
                stroke="var(--chart-invalid)"
                strokeDasharray="3 3"
                strokeWidth={2}
                dot={{
                  r: 3,
                  fill: "var(--chart-invalid)",
                  stroke: "var(--chart-surface)",
                  strokeWidth: 2,
                }}
                connectNulls={false}
                isAnimationActive={false}
                legendType="none"
              />
            ))}
            {codes.map((code) => (
              <Line
                key={code}
                dataKey={code}
                name={code}
                stroke={seriesColor(slots[code] ?? 0)}
                strokeWidth={2}
                dot={many ? false : { r: 4, strokeWidth: 0 }}
                activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--chart-surface)" }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul aria-label="Legend" className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {result.series.map((s) => (
          <li key={s.sensor_code} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-0.5 w-5 rounded"
              style={{ background: seriesColor(slots[s.sensor_code] ?? 0), height: 3 }}
            />
            <span>
              {s.sensor_code} · {s.sensor_name}
            </span>
          </li>
        ))}
        <li className="flex items-center gap-1.5 text-slate-600 dark:text-slate-400">
          <span
            aria-hidden="true"
            className="inline-block w-5 border-t-2 border-dashed"
            style={{ borderColor: "var(--chart-invalid)" }}
          />
          Below 75% complete
          <InfoTip label="completeness" text={GLOSSARY.completeness} />
        </li>
      </ul>
      {result.thresholds.length > 0 && thresholds.length === 0 && (
        <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
          Standards and heat triggers apply to daily figures; see Threshold alerts below
          {result.resolution !== "day"
            ? ", or choose the Daily resolution to see the 24-hour standard line"
            : ""}
          .
        </p>
      )}
    </div>
  );

  const shown = rows.slice(0, TABLE_ROW_LIMIT);
  const table = (
    <>
      <table className="w-full text-sm">
        <caption className="sr-only">
          {result.label} by {result.resolution} and sensor, in {result.unit}
        </caption>
        <thead>
          <tr className="text-left">
            <th scope="col" className="py-1 pr-2">
              Time
            </th>
            {codes.map((code) => (
              <th key={code} scope="col" className="py-1 pr-2 text-right">
                {code} ({result.unit})
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.t} className="border-t border-slate-200 dark:border-slate-800">
              <th scope="row" className="py-1 pr-2 text-left font-normal">
                {formatBucket(row.t)}
              </th>
              {codes.map((code) => {
                const p = points[code][row.t];
                return (
                  <td key={code} className="py-1 pr-2 text-right tabular-nums">
                    {p ? formatNumber(p.mean, result.variable) : "–"}
                    {p && !p.valid && <span className="text-amber-700"> (incomplete)</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > TABLE_ROW_LIMIT && (
        <p className="mt-1 text-xs text-slate-600">
          Showing the first {TABLE_ROW_LIMIT} of {rows.length} rows. Use Export for the full data.
        </p>
      )}
    </>
  );

  return (
    <ChartFrame
      id="timeseries"
      title={`${result.label} over time`}
      subtitle={`${result.series.length} sensor${result.series.length === 1 ? "" : "s"} · ${result.unit}`}
      chart={chart}
      table={table}
    />
  );
}
