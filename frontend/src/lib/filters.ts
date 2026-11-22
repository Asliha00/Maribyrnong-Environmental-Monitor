/** Filter defaults and client-side validation (UC2). The server re-checks everything. */
import type { Filters, Meta, Resolution } from "../api/data";

export const INVALID_RANGE_MESSAGE = "Invalid date range selected.";
export const HEATMAP_MAX_DAYS = 366;

function shiftDays(isoDate: string, days: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function daysInclusive(start: string, end: string): number {
  return (
    Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1
  );
}

/** Last 30 days of available data, daily temperature, all sensors, flagged excluded. */
export function defaultFilters(meta: Meta): Filters {
  const last = meta.data_range.last_day ?? new Date().toISOString().slice(0, 10);
  const first = meta.data_range.first_day ?? last;
  const candidate = shiftDays(last, -29);
  const variable = meta.variables.some((v) => v.variable === "temperature_c")
    ? "temperature_c"
    : (meta.variables[0]?.variable ?? "temperature_c");
  return {
    variable,
    resolution: "day",
    start: candidate < first ? first : candidate,
    end: last,
    landUses: [],
    sensorIds: [],
    excludeFlagged: true,
  };
}

/** A user-facing message if the filters cannot be applied, otherwise null. */
export function validateFilters(f: Filters, meta: Meta): string | null {
  if (!f.start || !f.end || f.start > f.end) return INVALID_RANGE_MESSAGE;
  const { first_day, last_day } = meta.data_range;
  if ((first_day && f.end < first_day) || (last_day && f.start > last_day)) {
    return INVALID_RANGE_MESSAGE;
  }
  const days = daysInclusive(f.start, f.end);
  const limits: Partial<Record<Resolution, number>> = {
    raw: meta.limits.raw_max_days,
    hour: meta.limits.hour_max_days,
  };
  const limit = limits[f.resolution];
  if (limit && days > limit) {
    const name = f.resolution === "raw" ? "Raw readings are" : "Hourly data is";
    return `${name} available for up to ${limit} days at a time. Choose a shorter range or another resolution.`;
  }
  return null;
}
