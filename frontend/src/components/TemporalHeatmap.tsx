import { useState } from "react";
import type { HeatmapResult } from "../api/data";
import { formatBucket, formatNumber, formatValue } from "../lib/format";
import { rampColor, SEQUENTIAL } from "../lib/palette";
import ChartFrame from "./ChartFrame";

const CELL_W = 34;
const CELL_H = 13;
const LEFT = 44;
const TOP = 22;

/**
 * UC2 visualisation 3: hour of day (rows) x month (columns). Colour = one blue ramp,
 * light (low) to dark (high); empty cells mean no valid hours. A 2px surface gap separates
 * cells; hover (or focus) shows the value.
 */
export default function TemporalHeatmap({ result }: { result: HeatmapResult }) {
  const [hover, setHover] = useState<{ month: string; hour: number } | null>(null);
  const min = result.summary.min ?? 0;
  const max = result.summary.max ?? 0;
  const byKey = new Map(result.cells.map((c) => [`${c.month}|${c.hour}`, c]));
  const width = LEFT + result.months.length * CELL_W;
  const height = TOP + 24 * CELL_H;
  const hovered = hover ? byKey.get(`${hover.month}|${hover.hour}`) : undefined;
  const fmt = (v: number | null | undefined) => formatValue(v, result.unit, result.variable);

  const chart = (
    <div>
      <div className="overflow-x-auto">
        <svg
          role="img"
          aria-label={`${result.label} by hour of day and month, ${formatValue(min, result.unit, result.variable)} to ${formatValue(max, result.unit, result.variable)}. The table view lists every value.`}
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="max-w-full"
        >
          {result.months.map((m, i) => (
            <text
              key={m}
              x={LEFT + i * CELL_W + CELL_W / 2}
              y={14}
              textAnchor="middle"
              fontSize={10}
              fill="var(--chart-muted)"
            >
              {formatBucket(m).replace(" 20", " ’")}
            </text>
          ))}
          {result.hours.map((h) => (
            <text
              key={h}
              x={LEFT - 6}
              y={TOP + h * CELL_H + CELL_H - 3}
              textAnchor="end"
              fontSize={10}
              fill="var(--chart-muted)"
            >
              {h % 3 === 0 ? `${String(h).padStart(2, "0")}:00` : ""}
            </text>
          ))}
          {result.months.map((m, i) =>
            result.hours.map((h) => {
              const cell = byKey.get(`${m}|${h}`);
              const isHover = hover?.month === m && hover.hour === h;
              return (
                <rect
                  key={`${m}-${h}`}
                  x={LEFT + i * CELL_W + 1}
                  y={TOP + h * CELL_H + 1}
                  width={CELL_W - 2}
                  height={CELL_H - 2}
                  rx={2}
                  fill={cell ? rampColor(cell.mean, min, max) : "transparent"}
                  stroke={isHover ? "var(--chart-ink)" : cell ? "none" : "var(--chart-grid)"}
                  strokeWidth={isHover ? 2 : 1}
                  onMouseEnter={() => setHover({ month: m, hour: h })}
                  onMouseLeave={() => setHover(null)}
                >
                  <title>
                    {`${formatBucket(m)}, ${String(h).padStart(2, "0")}:00 – ${cell ? fmt(cell.mean) : "no valid hours"}`}
                  </title>
                </rect>
              );
            }),
          )}
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-700 dark:text-slate-300">
        <span className="flex items-center gap-2">
          <span>{fmt(min)}</span>
          <span
            aria-hidden="true"
            className="h-3 w-28 rounded"
            style={{ background: `linear-gradient(to right, ${SEQUENTIAL.join(", ")})` }}
          />
          <span>{fmt(max)}</span>
        </span>
        <span>Empty cell = no valid hours</span>
        <span aria-live="polite" className="font-medium">
          {hovered && hover
            ? `${formatBucket(hover.month)} ${String(hover.hour).padStart(2, "0")}:00 – ${fmt(hovered.mean)} (${hovered.hours} hours)`
            : ""}
        </span>
      </div>
    </div>
  );

  const table = (
    <table className="text-xs">
      <caption className="sr-only">
        {result.label} ({result.unit}) by hour of day (rows) and month (columns)
      </caption>
      <thead>
        <tr>
          <th scope="col" className="pr-2 text-left">
            Hour
          </th>
          {result.months.map((m) => (
            <th key={m} scope="col" className="px-1 text-right">
              {formatBucket(m)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {result.hours.map((h) => (
          <tr key={h} className="border-t border-slate-200 dark:border-slate-800">
            <th scope="row" className="pr-2 text-left font-normal">
              {String(h).padStart(2, "0")}:00
            </th>
            {result.months.map((m) => {
              const c = byKey.get(`${m}|${h}`);
              return (
                <td key={m} className="px-1 text-right tabular-nums">
                  {c ? formatNumber(c.mean, result.variable) : "–"}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <ChartFrame
      id="heatmap"
      title={`${result.label}: daily and seasonal pattern`}
      subtitle={`Average by hour of day and month · ${result.sensors.join(", ")} · ${result.unit}`}
      chart={chart}
      table={table}
    />
  );
}
