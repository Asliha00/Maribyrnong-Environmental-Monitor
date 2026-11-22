import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { seriesColor } from "../../lib/palette";
import ChartFrame from "../ChartFrame";

/** Average day (hour-of-day means) per sensor, in each sensor's dashboard colour. */
export default function DiurnalChart({
  id,
  title,
  unit,
  series,
  slots,
}: {
  id: string;
  title: string;
  unit: string;
  series: { sensor_code: string; land_use: string; hours: (number | null)[] }[];
  slots: Record<string, number>;
}) {
  const rows = Array.from({ length: 24 }, (_, h) => ({
    hour: `${String(h).padStart(2, "0")}:00`,
    ...Object.fromEntries(series.map((s) => [s.sensor_code, s.hours[h]])),
  }));
  const table = (
    <table className="w-full text-right text-sm">
      <caption className="sr-only">{title}</caption>
      <thead>
        <tr>
          <th scope="col" className="text-left">
            Hour
          </th>
          {series.map((s) => (
            <th key={s.sensor_code} scope="col">
              {s.sensor_code} ({unit})
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.hour}>
            <th scope="row" className="text-left font-normal">
              {r.hour}
            </th>
            {series.map((s) => {
              const v = (r as Record<string, unknown>)[s.sensor_code] as number | null;
              return <td key={s.sensor_code}>{v === null ? "No data" : v.toFixed(1)}</td>;
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
  const chart = (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="hour" interval={2} tick={{ fill: "var(--chart-ink-2)", fontSize: 11 }} />
          <YAxis
            tick={{ fill: "var(--chart-ink-2)", fontSize: 11 }}
            width={48}
            label={{ value: unit, angle: -90, position: "insideLeft", fill: "var(--chart-ink-2)" }}
            domain={["auto", "auto"]}
          />
          <Tooltip
            contentStyle={{
              background: "var(--chart-surface)",
              border: "1px solid var(--chart-axis)",
            }}
            formatter={(v) => (typeof v === "number" ? `${v.toFixed(1)} ${unit}` : "No data")}
          />
          <Legend />
          {series.map((s) => (
            <Line
              key={s.sensor_code}
              dataKey={s.sensor_code}
              stroke={seriesColor(slots[s.sensor_code] ?? 0)}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
  return <ChartFrame id={id} title={title} chart={chart} table={table} />;
}
