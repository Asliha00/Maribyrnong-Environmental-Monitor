/** Formatting with units on every number (usability NFR). */
const DECIMALS: Record<string, number> = {
  temperature_c: 1,
  humidity_pct: 0,
  pm1: 1,
  pm25: 1,
  pm10: 1,
  no2_ppb: 0,
  co_ppb: 0,
  co2_ppm: 0,
  pressure_hpa: 1,
};

export function formatNumber(value: number | null | undefined, variable?: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return value.toLocaleString("en-AU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: variable ? (DECIMALS[variable] ?? 1) : 1,
  });
}

export function formatValue(
  value: number | null | undefined,
  unit: string,
  variable?: string,
): string {
  const number = formatNumber(value, variable);
  if (number === "–") return "No data";
  return unit === "%" ? `${number}%` : `${number} ${unit}`;
}

/** A UTC timestamp shown in Melbourne local time, e.g. "16 Feb 2026, 11:42 pm". */
export function formatMelbourne(isoUtc: string | null | undefined): string {
  if (!isoUtc) return "Unknown";
  const date = new Date(isoUtc);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString("en-AU", {
    timeZone: "Australia/Melbourne",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Bucket labels from the API ("2025-07-15", "2025-07", "2025-07-15 14:00") made readable. */
export function formatBucket(t: string): string {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  if (day) return `${Number(day[3])} ${MONTHS[Number(day[2]) - 1]} ${day[1]}`;
  const month = /^(\d{4})-(\d{2})$/.exec(t);
  if (month) return `${MONTHS[Number(month[2]) - 1]} ${month[1]}`;
  const hour = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):00$/.exec(t);
  if (hour) return `${Number(hour[3])} ${MONTHS[Number(hour[2]) - 1]} ${hour[4]}:00`;
  const raw = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(t);
  if (raw) return `${Number(raw[3])} ${MONTHS[Number(raw[2]) - 1]} ${raw[4]}:${raw[5]}`;
  return t; // seasons ("Winter 2025") are already readable
}
