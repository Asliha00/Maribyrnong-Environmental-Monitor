/** Shaping API series for charts and tables (pure, unit-tested). */
import type { Point, Resolution, Series, Threshold } from "../api/data";

export type ChartRow = { t: string } & Record<string, number | null | string>;

const SEASON = /^(Summer|Autumn|Winter|Spring)/;

/**
 * One row per bucket. For each sensor code: `<code>` holds the value of a VALID bucket
 * (else null) and `<code>__invalid` the value of an invalid (<75% complete) bucket, which
 * the chart draws greyed. `points[code][t]` keeps the full point for tooltips and tables.
 */
export function mergeSeries(series: Series[]): {
  rows: ChartRow[];
  points: Record<string, Record<string, Point>>;
} {
  const order: string[] = [];
  const seen = new Set<string>();
  const points: Record<string, Record<string, Point>> = {};
  for (const s of series) {
    points[s.sensor_code] = {};
    for (const p of s.points) {
      points[s.sensor_code][p.t] = p;
      if (!seen.has(p.t)) {
        seen.add(p.t);
        order.push(p.t);
      }
    }
  }
  // ISO buckets sort as text; season labels already arrive in time order
  const sorted = SEASON.test(order[0] ?? "") ? order : [...order].sort();
  const rows = sorted.map((t) => {
    const row: ChartRow = { t };
    for (const s of series) {
      const p = points[s.sensor_code][t];
      row[s.sensor_code] = p && p.valid ? p.mean : null;
      row[`${s.sensor_code}__invalid`] = p && !p.valid ? p.mean : null;
    }
    return row;
  });
  return { rows, points };
}

/**
 * Threshold lines only where they measure the same statistic as the plotted value: a
 * 24-hour-mean standard over DAILY means. Daily-maximum (hot-day) triggers are not drawn
 * over means; they appear in the Threshold alerts panel instead.
 */
export function thresholdsToDraw(thresholds: Threshold[], resolution: Resolution): Threshold[] {
  return resolution === "day" ? thresholds.filter((t) => t.period === "day") : [];
}
