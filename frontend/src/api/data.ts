/**
 * Typed calls to the data API (Phase 2 + /api/heatmap). Every call uses the UC2
 * 5-second timeout; error text comes from the server (or the client's timeout and
 * network messages) and is shown verbatim.
 */
import { apiGetData, apiPostFile } from "./client";

export type Resolution = "hour" | "day" | "month" | "season" | "raw";

export type VariableMeta = { variable: string; label: string; unit: string; sensor_count: number };
export type Threshold = {
  threshold_id: number;
  variable: string;
  period: string; // "day" (24-hour mean) | "day_max" (daily maximum)
  operator: string;
  value: number;
  label: string;
  source: string | null;
};
export type Meta = {
  variables: VariableMeta[];
  land_uses: string[];
  resolutions: Resolution[];
  data_range: { first_day: string | null; last_day: string | null };
  thresholds: Threshold[];
  limits: { raw_max_days: number; hour_max_days: number; max_sensor_ids: number };
};

export type SensorVariable = { variable: string; label: string; unit: string };
export type Sensor = {
  sensor_id: number;
  sensor_code: string;
  sensor_name: string;
  device_family: string;
  land_use: string;
  status: string;
  latitude: number | null;
  longitude: number | null;
  location_verified: boolean;
  variables: SensorVariable[];
  latest: { ts_utc: string | null; ts_local: string; values: Record<string, number | null> } | null;
  completeness: Record<
    string,
    { avg_daily_pct: number | null; valid_days: number; days_with_data: number } | null
  >;
  first_reading_utc: string | null;
  last_reading_utc: string | null;
  quality_notes: string[];
};

export type Point = {
  t: string;
  mean: number | null;
  min: number | null;
  max: number | null;
  n: number;
  completeness_pct: number | null;
  valid: boolean;
  flagged: boolean;
};
export type Summary = {
  mean: number | null;
  min: number | null;
  max: number | null;
  n: number;
  completeness_pct: number | null;
  valid_buckets: number;
  buckets: number;
};
export type Series = {
  sensor_id: number;
  sensor_code: string;
  sensor_name: string;
  land_use: string;
  location_verified: boolean;
  points: Point[];
  summary: Summary;
};
export type ReadingsResult = {
  variable: string;
  label: string;
  unit: string;
  resolution: Resolution;
  start: string;
  end: string;
  exclude_flagged: boolean;
  series: Series[];
  summary: Summary;
  thresholds: Threshold[];
  notes: string[];
};

export type HeatmapResult = {
  variable: string;
  label: string;
  unit: string;
  start: string;
  end: string;
  months: string[];
  hours: number[];
  cells: { month: string; hour: number; mean: number; n: number; hours: number }[];
  sensors: string[];
  summary: { min: number | null; max: number | null };
  notes: string[];
};

export type Exceedance = {
  date_local: string;
  sensor_id: number;
  sensor_code: string;
  sensor_name: string;
  land_use: string;
  threshold_id: number;
  label: string;
  variable: string;
  unit: string;
  statistic: string;
  observed_value: number;
  threshold_value: number;
  operator: string;
  completeness_pct: number | null;
};
export type ExceedancesResult = { total: number; items: Exceedance[] };

export type Filters = {
  variable: string;
  resolution: Resolution;
  start: string;
  end: string;
  landUses: string[];
  sensorIds: number[];
  excludeFlagged: boolean;
};

/** Query string with repeated keys for lists (land_use=A&land_use=B), as FastAPI expects. */
export function filterQuery(f: Filters, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams({
    variable: f.variable,
    start: f.start,
    end: f.end,
    exclude_flagged: String(f.excludeFlagged),
    ...extra,
  });
  f.landUses.forEach((l) => params.append("land_use", l));
  f.sensorIds.forEach((s) => params.append("sensor_ids", String(s)));
  return params.toString();
}

export const getMeta = () => apiGetData<Meta>("/meta");
export const getSensors = () => apiGetData<{ sensors: Sensor[] }>("/sensors");
export const getSensor = (id: number) => apiGetData<Sensor>(`/sensors/${id}`);
export const getReadings = (f: Filters) =>
  apiGetData<ReadingsResult>(`/readings?${filterQuery(f, { resolution: f.resolution })}`);
export const getHeatmap = (f: Filters) => apiGetData<HeatmapResult>(`/heatmap?${filterQuery(f)}`);

export function getExceedances(
  f: Pick<Filters, "start" | "end" | "landUses" | "sensorIds"> & { variable?: string },
  sort: "date" | "value" | "sensor",
  order: "asc" | "desc",
) {
  const params = new URLSearchParams({ start: f.start, end: f.end, sort, order, limit: "500" });
  if (f.variable) params.set("variable", f.variable);
  f.landUses.forEach((l) => params.append("land_use", l));
  f.sensorIds.forEach((s) => params.append("sensor_ids", String(s)));
  return apiGetData<ExceedancesResult>(`/exceedances?${params.toString()}`);
}

export type ExportFormat = "csv" | "pdf";

/** UC3: the applied filters as a file. `confirmLarge` after the >50,000-row warning. */
export const exportReport = (f: Filters, format: ExportFormat, confirmLarge = false) =>
  apiPostFile("/reports/export", {
    format,
    variable: f.variable,
    resolution: f.resolution,
    start: f.start,
    end: f.end,
    land_use: f.landUses,
    sensor_ids: f.sensorIds,
    exclude_flagged: f.excludeFlagged,
    confirm_large: confirmLarge,
  });
